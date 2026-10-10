"""End-to-end API tests: CSV -> raw storage -> validation -> database -> API.

They use an in-memory SQLite database by default. Set TEST_DATABASE_URL to run
them against PostgreSQL (CI does this), e.g.
postgresql+psycopg://recytrack:recytrack@localhost:5432/recytrack_test
"""
import csv
import io
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.repository import SqlRepository
from app.database.tables import Base, MaterialEventRow, RawRecordRow
from app.main import DB_UNAVAILABLE, create_app
from app.pipeline import run_csv_ingestion

HEADER = "source_record_id,facility_id,material_name,event_type,quantity,unit,event_timestamp,batch_id\n"


@pytest.fixture
def app():
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    app = create_app(url, init_attempts=1)
    Base.metadata.drop_all(app.state.engine)  # start every test from an empty database
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def upload(client, fixtures_dir):
    def _upload(name: str, content: bytes | None = None):
        data = content if content is not None else (fixtures_dir / name).read_bytes()
        return client.post("/api/v1/ingestion/csv", files={"file": (name, data, "text/csv")})

    return _upload


def count(app, model) -> int:
    with app.state.sessionmaker() as s:
        return s.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------- health


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert "/api/v1/ingestion/csv" in client.get("/openapi.json").json()["paths"]


# ---------------------------------------------------------------- ingestion


def test_import_valid_fixture(app, upload, client):
    r = upload("valid_events.csv")
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "SUCCEEDED"
    assert run["file_name"] == "valid_events.csv"
    assert (run["received_count"], run["accepted_count"], run["quarantined_count"]) == (10, 10, 0)
    assert count(app, RawRecordRow) == 10
    assert count(app, MaterialEventRow) == 10

    runs = client.get("/api/v1/ingestion/runs").json()
    assert runs["total"] == 1 and runs["items"][0]["run_id"] == run["run_id"]
    assert client.get(f"/api/v1/ingestion/runs/{run['run_id']}").json()["accepted_count"] == 10


def test_raw_rows_are_stored_exactly(app, upload):
    upload("valid_events.csv")
    with app.state.sessionmaker() as s:
        raw = s.scalar(select(RawRecordRow).where(RawRecordRow.source_record_id == "SRC-1008"))
    assert raw.raw_payload["material_name"] == "  recycled   resin "
    assert raw.row_number == 9
    assert len(raw.payload_hash) == 64


def test_import_invalid_fixture_counts(upload):
    run = upload("invalid_events.csv").json()
    assert (run["received_count"], run["accepted_count"], run["quarantined_count"],
            run["flagged_count"], run["duplicate_count"]) == (15, 2, 9, 3, 1)


def test_labeled_outcomes_are_persisted(app, upload, fixtures_dir):
    upload("invalid_events.csv")
    with open(fixtures_dir / "expected_outcomes.csv", newline="") as f:
        expected = [r for r in csv.DictReader(f) if r["fixture"] == "invalid_events.csv"]
    with app.state.sessionmaker() as s:
        stored = {
            raw.row_number: event
            for event, raw in s.execute(select(MaterialEventRow, RawRecordRow).join(MaterialEventRow.raw))
        }
        for row in expected:
            n = int(row["row_number"])
            if row["expected_status"] == "DUPLICATE":
                assert n not in stored  # no second event for a duplicate
                continue
            assert stored[n].validation_status == row["expected_status"], row
            assert {i.rule_code for i in stored[n].issues} == set(filter(None, row["expected_rule_codes"].split(";")))


def test_reimport_does_not_duplicate_events(app, upload):
    first = upload("valid_events.csv").json()
    second = upload("valid_events.csv").json()
    assert second["accepted_count"] == 0
    assert second["duplicate_count"] == 10
    assert second["run_id"] != first["run_id"]
    assert count(app, MaterialEventRow) == 10
    assert count(app, RawRecordRow) == 20  # raw rows of both runs are traceable


def test_database_rejects_duplicate_event(app, client, fixtures_dir):
    """The unique constraint backs up VAL-007 if two imports race."""
    data = (fixtures_dir / "valid_events.csv").read_bytes()
    with app.state.sessionmaker() as s:
        run_csv_ingestion(data, SqlRepository(s))
        s.commit()

    class BlindRepository(SqlRepository):
        def find_hashes_for_keys(self, keys):
            return {}  # simulates a concurrent run that has not seen the first commit

    with app.state.sessionmaker() as s:
        with pytest.raises(IntegrityError):
            run_csv_ingestion(data, BlindRepository(s))
            s.commit()


@pytest.mark.parametrize(
    "name, content, status, message",
    [
        ("events.txt", b"x", 415, "not a .csv file"),
        ("empty.csv", b"", 422, "empty"),
        ("bad.csv", b"a,b\n1,2\n", 422, "missing columns"),
    ],
)
def test_bad_files_get_actionable_errors(app, upload, name, content, status, message):
    r = upload(name, content)
    assert r.status_code == status
    assert message in str(r.json()["detail"])


def test_failed_run_is_recorded(client, upload):
    detail = upload("bad.csv", b"a,b\n1,2\n").json()["detail"]
    assert detail["run"]["status"] == "FAILED"
    runs = client.get("/api/v1/ingestion/runs", params={"status": "failed"}).json()
    assert runs["total"] == 1


def test_upload_size_limit(upload, monkeypatch):
    monkeypatch.setattr("app.api.routes.MAX_UPLOAD_BYTES", 100)
    r = upload("big.csv", HEADER.encode() * 5)
    assert r.status_code == 413


# ---------------------------------------------------------------- records


def test_records_filters_and_pagination(client, upload):
    upload("valid_events.csv")
    get = lambda **p: client.get("/api/v1/records", params=p).json()

    assert get()["total"] == 10
    page = get(page_size=3, page=2)
    assert (page["total"], len(page["items"]), page["page"]) == (10, 3, 2)
    assert get(facility_id="fac-02")["total"] == 4
    assert get(material_code="RECYCLED_RESIN")["total"] == 4
    assert get(event_type="receipt")["total"] == 4
    assert get(batch_id="BATCH-42")["total"] == 3
    assert get(date_from="2026-10-03T00:00:00Z", date_to="2026-10-04T00:00:00Z")["total"] == 2
    assert get(status="QUARANTINED")["total"] == 0
    assert get(facility_id="FAC-02")["filters"] == {"facility_id": "FAC-02"}


def test_records_are_normalized(client, upload):
    upload("valid_events.csv")
    items = {i["source_record_id"]: i for i in client.get("/api/v1/records", params={"page_size": 50}).json()["items"]}
    lb = items["SRC-1002"]
    assert lb["unit_raw"] == "lb" and lb["unit"] == "lb"
    assert Decimal(lb["quantity_kg"]) == Decimal("2204.62") * Decimal("0.45359237")
    assert items["SRC-1003"]["event_timestamp"].startswith("2026-10-02T06:15:00")
    assert items["SRC-1003"]["event_timestamp_raw"] == "2026-10-02T08:15:00+02:00"
    assert items["SRC-1006"]["quantity"] == "-12.5"
    assert items["SRC-1008"]["material_code"] == "RECYCLED_RESIN"


# ---------------------------------------------------------------- quarantine


def test_quarantine_list_and_filters(client, upload):
    upload("invalid_events.csv")
    get = lambda **p: client.get("/api/v1/quarantine", params=p).json()
    assert get()["total"] == 12  # 9 quarantined + 3 flagged
    assert get(status="FLAGGED")["total"] == 3
    timestamps = get(rule_code="VAL-005")
    assert timestamps["total"] == 2
    assert all(i["issues"][0]["rule_code"] == "VAL-005" for i in timestamps["items"])


def test_exception_detail_traces_to_source(client, upload):
    run = upload("invalid_events.csv").json()
    item = next(i for i in client.get("/api/v1/quarantine", params={"rule_code": "VAL-004"}).json()["items"])
    detail = client.get(f"/api/v1/quarantine/{item['event_id']}").json()

    assert detail["raw"]["raw_payload"]["unit"] == "tons"
    assert detail["raw"]["row_number"] == 3
    assert detail["run"]["run_id"] == run["run_id"]
    assert detail["event"]["validation_status"] == "QUARANTINED"
    assert detail["issues"][0]["raw_value"] == "tons"
    assert detail["issues"][0]["review_status"] == "OPEN"
    assert detail["review_history"] == []


def test_exception_detail_not_found(client, upload):
    upload("valid_events.csv")
    accepted = client.get("/api/v1/records").json()["items"][0]["event_id"]
    assert client.get(f"/api/v1/quarantine/{accepted}").status_code == 404
    assert client.get("/api/v1/quarantine/nope").status_code == 404


def test_review_decision_is_audited_and_source_unchanged(client, upload):
    upload("invalid_events.csv")
    item = client.get("/api/v1/quarantine", params={"rule_code": "VAL-008"}).json()["items"][0]
    before = client.get(f"/api/v1/quarantine/{item['event_id']}").json()

    r = client.patch(
        f"/api/v1/quarantine/{item['event_id']}/review",
        json={"review_status": "APPROVED", "actor_label": "analyst-1", "note": "New material, alias to be added"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["audit"]["details"]["previous_review_status"] == ["OPEN"]

    after = client.get(f"/api/v1/quarantine/{item['event_id']}").json()
    assert after["issues"][0]["review_status"] == "APPROVED"
    assert after["review_history"][0]["actor_label"] == "analyst-1"
    assert after["raw"] == before["raw"]
    assert after["event"] == before["event"]  # source and normalized values are not rewritten

    assert client.get("/api/v1/quarantine", params={"review_status": "OPEN"}).json()["total"] == 11


@pytest.mark.parametrize(
    "body",
    [
        {"review_status": "APPROVED", "actor_label": ""},
        {"review_status": "MAYBE", "actor_label": "a"},
        {"actor_label": "a"},
    ],
)
def test_review_rejects_bad_input(client, upload, body):
    upload("invalid_events.csv")
    item = client.get("/api/v1/quarantine").json()["items"][0]
    assert client.patch(f"/api/v1/quarantine/{item['event_id']}/review", json=body).status_code == 422


# ---------------------------------------------------------------- metrics


def test_quality_metrics(client, upload):
    valid = upload("valid_events.csv").json()
    upload("invalid_events.csv")
    m = client.get("/api/v1/metrics/quality").json()
    assert (m["runs"], m["received"], m["accepted"], m["quarantined"], m["flagged"], m["duplicates"]) == (2, 25, 12, 9, 3, 1)
    assert m["acceptance_rate"] == 0.48
    assert m["open_exceptions"] == 12
    assert m["issues_by_rule"]["VAL-005"] == 2

    one = client.get("/api/v1/metrics/quality", params={"run_id": valid["run_id"]}).json()
    assert (one["received"], one["accepted"], one["open_exceptions"]) == (10, 10, 0)
    assert client.get("/api/v1/metrics/quality", params={"run_id": "nope"}).status_code == 404


def test_metrics_on_empty_database(client):
    m = client.get("/api/v1/metrics/quality").json()
    assert m["runs"] == 0 and m["acceptance_rate"] is None


# ---------------------------------------------------------------- exports


def read_csv(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    return list(csv.DictReader(io.StringIO(response.text)))


def test_exceptions_csv(client, upload):
    upload("invalid_events.csv")
    rows = read_csv(client.get("/api/v1/reports/exceptions.csv"))
    assert len(rows) == 12  # one issue per exception in this fixture
    tons = next(r for r in rows if r["rule_code"] == "VAL-004")
    assert (tons["raw_value"], tons["row_number"], tons["review_status"]) == ("tons", "3", "OPEN")
    assert len(read_csv(client.get("/api/v1/reports/exceptions.csv", params={"status": "FLAGGED"}))) == 3


def test_records_csv(client, upload):
    upload("valid_events.csv")
    rows = read_csv(client.get("/api/v1/reports/records.csv", params={"facility_id": "FAC-01"}))
    assert len(rows) == 6
    assert next(r for r in rows if r["source_record_id"] == "SRC-1006")["quantity"] == "-12.5"


def test_csv_export_neutralizes_formulas(client, upload):
    row = 'SRC-9,FAC-01,"=HYPERLINK(""http://x"")",RECEIPT,1,kg,2026-10-01T09:00:00Z,\n'
    upload("evil.csv", (HEADER + row).encode())
    rows = read_csv(client.get("/api/v1/reports/exceptions.csv"))
    assert rows[0]["material_name_raw"].startswith("'=HYPERLINK")


# ---------------------------------------------------------------- database down


def test_database_unavailable_returns_503_without_secrets():
    app = create_app("postgresql+psycopg://user:s3cret@127.0.0.1:1/nodb", init_attempts=1)
    client = TestClient(app)  # no context manager: skip startup so requests hit the dead database
    health = client.get("/health")
    assert health.status_code == 503 and health.json()["database"] == "unavailable"

    r = client.get("/api/v1/ingestion/runs")
    assert r.status_code == 503
    assert r.json()["detail"] == DB_UNAVAILABLE
    assert "s3cret" not in r.text
