"""Simulated API source -> pipeline -> database -> API (M7).

Like test_api.py these use in-memory SQLite by default; set TEST_DATABASE_URL to run them on PostgreSQL.
The simulator is reached in-process through an httpx transport, with no network.
"""
import csv
import dataclasses
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database.tables import Base, IngestionRunRow, MaterialEventRow, RawRecordRow
from app.ingestion.api_records import records_from_api_items
from app.main import create_app
from app.pipeline import run_api_ingestion
from app.store import InMemoryRepository
from simulator.main import create_app as create_simulator
from tests.conftest import simulator_transport

IMPORT = "/api/v1/ingestion/simulated-api"


@pytest.fixture
def app():
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    app = create_app(url, init_attempts=1)
    Base.metadata.drop_all(app.state.engine)
    app.state.source_settings = dataclasses.replace(app.state.source_settings, url="http://127.0.0.1:8001", backoff_s=0)
    app.state.source_transport = simulator_transport(create_simulator("none"))
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def count(app, model) -> int:
    with app.state.sessionmaker() as s:
        return s.scalar(select(func.count()).select_from(model))


def expected_outcomes(fixtures_dir):
    with open(fixtures_dir / "simulated_expected_outcomes.csv", newline="") as f:
        return list(csv.DictReader(f))


def rule_codes(row) -> set[str]:
    return set(filter(None, row["expected_rule_codes"].split(";")))


def test_import_from_simulator_gives_expected_counts(app, client):
    r = client.post(IMPORT)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "SUCCEEDED"
    assert run["source_name"] == "simulated_api"
    assert run["file_name"] == "GET /v1/events"
    assert (run["received_count"], run["accepted_count"], run["quarantined_count"],
            run["flagged_count"], run["duplicate_count"]) == (200, 180, 14, 6, 0)
    assert count(app, RawRecordRow) == 200
    assert count(app, MaterialEventRow) == 200


def test_labeled_outcomes_match(app, client, fixtures_dir):
    client.post(IMPORT)
    expected = expected_outcomes(fixtures_dir)
    assert len(expected) == 200
    with app.state.sessionmaker() as s:
        stored = {
            raw.row_number: event
            for event, raw in s.execute(select(MaterialEventRow, RawRecordRow).join(MaterialEventRow.raw))
        }
        for row in expected:
            event = stored[int(row["row_number"])]
            assert event.source_record_id == row["source_record_id"], row
            assert event.validation_status == row["expected_status"], row
            assert {i.rule_code for i in event.issues} == rule_codes(row), row


def test_labeled_outcomes_match_in_memory(fixtures_dir):
    """The same check through the pure pipeline, without a database."""
    transport = simulator_transport(create_simulator("none"))
    items = httpx.Client(transport=transport, base_url="http://sim").get("/v1/events").json()["items"]
    result = run_api_ingestion(items, InMemoryRepository())
    by_row = dict(enumerate(result.events, start=1))
    for row in expected_outcomes(fixtures_dir):
        event = by_row[int(row["row_number"])]
        assert event.validation_status.value == row["expected_status"], row
        assert {i.rule_code for i in event.issues} == rule_codes(row), row


def test_reimport_adds_no_events(app, client):
    client.post(IMPORT)
    events = count(app, MaterialEventRow)
    again = client.post(IMPORT).json()
    assert again["status"] == "SUCCEEDED"
    assert count(app, MaterialEventRow) == events
    assert again["accepted_count"] == 0
    # Only events after the latest stored time are fetched; the file name shows the cursor.
    assert again["file_name"] == "GET /v1/events?since=2026-10-25T22:41:00+00:00"


def test_reimport_with_explicit_since_counts_duplicates(app, client):
    client.post(IMPORT)
    again = client.post(IMPORT, json={"since": "2026-09-30T00:00:00Z"}).json()
    assert (again["received_count"], again["duplicate_count"], again["accepted_count"]) == (200, 200, 0)
    assert count(app, MaterialEventRow) == 200


def test_since_must_have_an_offset(client):
    assert client.post(IMPORT, json={"since": "2026-10-01T00:00:00"}).status_code == 422


def test_source_json_is_preserved(app, client):
    client.post(IMPORT)
    with app.state.sessionmaker() as s:
        raw = s.scalar(select(RawRecordRow).where(RawRecordRow.source_record_id == "SIM-0004"))
    original = json.loads(raw.raw_payload["_source_json"])
    assert "qty" not in original  # the faulty item is kept exactly as sent
    assert raw.raw_payload["quantity"] == ""
    assert raw.raw_payload["_source_json"] == json.dumps(original, sort_keys=True, separators=(",", ":"))
    assert raw.row_number == 4


def test_field_mapping_keeps_values_exactly():
    item = {"id": " SIM-9 ", "facility": "fac-20", "material": "Plastic film", "type": "receipt", "qty": "1,200.50",
            "unit": "KG", "occurred_at": "2026-10-01T06:00:00Z", "batch": None}
    (raw,) = records_from_api_items([item], "run-1")
    assert dict(raw.payload) == {
        "source_record_id": " SIM-9 ", "facility_id": "fac-20", "material_name": "Plastic film",
        "event_type": "receipt", "quantity": "1,200.50", "unit": "KG", "event_timestamp": "2026-10-01T06:00:00Z",
        "batch_id": "", "_source_json": json.dumps(item, sort_keys=True, separators=(",", ":")),
    }
    assert (raw.row_number, raw.source_name) == (1, "simulated_api")


def test_unexpected_keys_make_an_item_structurally_suspect():
    item = {"id": "SIM-1", "facility": "FAC-20", "material": "Plastic film", "type": "RECEIPT", "qty": "10",
            "unit": "kg", "occurred_at": "2026-10-01T06:00:00Z", "batch": "B", "colour": "blue"}
    result = run_api_ingestion([item], InMemoryRepository())
    (event,) = result.events
    assert event.validation_status.value == "QUARANTINED"
    assert [(i.rule_code, i.raw_value) for i in event.issues] == [("VAL-001", '["colour"]')]


def test_source_down_gives_502_and_a_failed_run(app, client):
    app.state.source_transport = simulator_transport(create_simulator("always_500"))
    r = client.post(IMPORT)
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["message"] == (
        "Simulated source at http://127.0.0.1:8001 unreachable after 3 attempts (last error: HTTP 500). "
        "Check that the simulator is running."
    )
    assert detail["run"]["status"] == "FAILED"
    assert detail["run"]["error_summary"] == detail["message"]
    with app.state.sessionmaker() as s:
        run = s.get(IngestionRunRow, detail["run"]["run_id"])
        assert run.status == "FAILED" and run.source_name == "simulated_api"
    assert count(app, MaterialEventRow) == 0


def test_unreachable_source_gives_502(app, client):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    app.state.source_transport = httpx.MockTransport(refuse)
    r = client.post(IMPORT)
    assert r.status_code == 502
    assert "last error: connection error" in r.json()["detail"]["message"]


def test_source_4xx_gives_502_without_retries(app, client):
    calls = []

    def not_found(request):
        calls.append(request)
        return httpx.Response(404, json={"detail": "Not Found"})

    app.state.source_transport = httpx.MockTransport(not_found)
    r = client.post(IMPORT)
    assert r.status_code == 502
    assert "HTTP 404" in r.json()["detail"]["message"]
    assert r.json()["detail"]["run"]["status"] == "FAILED"
    assert len(calls) == 1


def test_flaky_source_recovers(app, client):
    app.state.source_transport = simulator_transport(create_simulator("flaky"))
    r = client.post(IMPORT)
    assert r.status_code == 201
    assert r.json()["received_count"] == 200
