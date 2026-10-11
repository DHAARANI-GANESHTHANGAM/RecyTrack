"""End-to-end reconciliation tests: CSV -> validation -> database -> POST /reconciliations.

Like test_api.py they use in-memory SQLite by default; set TEST_DATABASE_URL to run
them against PostgreSQL.
"""
import csv
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.tables import AuditEventRow, Base, ReconciliationEventRow
from app.main import create_app

PERIOD = {"period_start": "2026-10-01T00:00:00Z", "period_end": "2026-10-31T23:59:59Z"}


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
def scenarios(client, fixtures_dir):
    data = (fixtures_dir / "reconciliation_scenarios.csv").read_bytes()
    r = client.post("/api/v1/ingestion/csv", files={"file": ("reconciliation_scenarios.csv", data, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def expected(fixtures_dir):
    with open(fixtures_dir / "expected_reconciliations.csv", newline="") as f:
        return list(csv.DictReader(f))


def reconcile(client, facility_id, material_code="PLASTIC_FILM", **extra):
    body = {"facility_id": facility_id, "material_code": material_code, **PERIOD, **extra}
    return client.post("/api/v1/reconciliations", json=body)


def dec(value):
    return None if value in (None, "") else Decimal(value)


def test_scenarios_import_cleanly(scenarios):
    # 33 rows; only the -10 kg shipment of FAC-15 is flagged (VAL-003).
    assert (scenarios["received_count"], scenarios["accepted_count"], scenarios["flagged_count"]) == (33, 32, 1)


def test_expected_reconciliations(client, scenarios, expected):
    assert len(expected) == 7
    for row in expected:
        r = client.post(
            "/api/v1/reconciliations",
            json={
                "facility_id": row["facility_id"],
                "material_code": row["material_code"],
                "period_start": row["period_start"],
                "period_end": row["period_end"],
            },
        )
        assert r.status_code == 201, (row["scenario"], r.text)
        body = r.json()
        assert body["status"] == row["expected_status"], (row["scenario"], body["reasons"])
        assert dec(body["variance_kg"]) == dec(row["expected_variance_kg"]), row["scenario"]
        assert dec(body["tolerance_kg"]) == dec(row["expected_tolerance_kg"]), row["scenario"]


def test_detail_links_events_and_shows_formula(client, scenarios):
    created = reconcile(client, "FAC-10").json()
    detail = client.get(f"/api/v1/reconciliations/{created['reconciliation_id']}").json()
    assert detail == created

    ids = {role: [e["source_record_id"] for e in events] for role, events in detail["events"].items()}
    assert ids["opening_count"] == ["REC-1001"]
    assert ids["receipt"] == ["REC-1002"]
    assert ids["consumption"] == ["REC-1003"]
    assert ids["loss"] == ["REC-1004"]
    assert ids["closing_count"] == ["REC-1005"]
    assert ids["excluded"] == [] and ids["intermediate_count"] == []
    receipt = detail["events"]["receipt"][0]
    assert (receipt["event_type"], receipt["quantity_kg"]) == ("RECEIPT", "500")
    assert receipt["event_timestamp"].startswith("2026-10-05T09:00:00")

    assert (detail["opening_stock_kg"], detail["expected_closing_kg"], detail["throughput_kg"]) == ("1000", "280", "1500")
    assert "= 280" in detail["formula"] and "1200 consumption" in detail["formula"]
    assert "max of 5 kg absolute, 1.0% of throughput 1500 kg" in detail["tolerance_explanation"]
    assert detail["reasons"] == ["|variance| 0 kg is within tolerance 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg)"]


def test_pound_receipt_is_traced_in_kg(client, scenarios):
    detail = reconcile(client, "FAC-14").json()
    assert detail["events"]["receipt"][0]["quantity_kg"] == "1000.17117585"
    assert detail["variance_kg"] == "-0.17117585"


def test_needs_review_wording(client, scenarios):
    body = reconcile(client, "FAC-11").json()
    assert body["status"] == "NEEDS_REVIEW"
    assert body["reasons"] == [
        "|variance| 80 kg exceeds tolerance 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg). "
        "This is a flag for review, not proof of an error"
    ]


def test_missing_closing_count_reason(client, scenarios):
    body = reconcile(client, "FAC-12").json()
    assert body["status"] == "NEEDS_DATA"
    assert body["closing_stock_kg"] is None and body["expected_closing_kg"] == "280"
    assert body["reasons"] == ["No INVENTORY_COUNT after 2026-10-01T00:00:00Z and at or before 2026-10-31T23:59:59Z"]


def test_custom_tolerance(client, scenarios):
    body = reconcile(client, "FAC-11", absolute_tolerance_kg="100", percent_tolerance="0").json()
    assert body["status"] == "WITHIN_TOLERANCE"
    assert (body["tolerance_kg"], body["tolerance_absolute_kg"], body["tolerance_percent"]) == ("100", "100", "0")


def test_facility_and_material_are_case_insensitive(client, scenarios):
    body = reconcile(client, " fac-10 ", "plastic_film").json()
    assert (body["facility_id"], body["material_code"], body["status"]) == ("FAC-10", "PLASTIC_FILM", "WITHIN_TOLERANCE")


def test_list_filters_newest_first(client, scenarios):
    for facility in ("FAC-10", "FAC-11", "FAC-12"):
        assert reconcile(client, facility).status_code == 201
    assert reconcile(client, "FAC-14", "RECYCLED_RESIN").status_code == 201
    get = lambda **p: client.get("/api/v1/reconciliations", params=p).json()

    everything = get()
    assert everything["total"] == 4
    created = [i["created_at"] for i in everything["items"]]
    assert created == sorted(created, reverse=True)
    assert get(facility_id="fac-10")["items"][0]["facility_id"] == "FAC-10"
    assert get(facility_id="FAC-10")["total"] == 1
    assert get(material_code="recycled_resin")["total"] == 1
    assert get(status="NEEDS_REVIEW")["items"][0]["facility_id"] == "FAC-11"
    assert get(status="within_tolerance")["total"] == 2
    assert get(status="NEEDS_DATA", facility_id="FAC-12")["total"] == 1
    assert get(page_size=1, page=2)["page"] == 2 and len(get(page_size=1, page=2)["items"]) == 1
    assert get(status="NEEDS_DATA")["filters"] == {"status": "NEEDS_DATA"}


def test_unknown_reconciliation_is_404(client):
    assert client.get("/api/v1/reconciliations/nope").status_code == 404


@pytest.mark.parametrize(
    "override",
    [
        {"period_end": "2026-10-01T00:00:00Z"},  # equal to period_start
        {"period_end": "2026-09-30T00:00:00Z"},  # before period_start
        {"period_start": "2026-10-01T00:00:00"},  # no offset
        {"period_end": "2026-10-31T23:59:59"},  # no offset
        {"material_code": "GLASS"},
        {"facility_id": ""},
        {"facility_id": "   "},
        {"absolute_tolerance_kg": "-1"},
        {"percent_tolerance": "-0.5"},
        {"actor_label": ""},
    ],
)
def test_bad_requests_are_422(client, override):
    body = {"facility_id": "FAC-10", "material_code": "PLASTIC_FILM", **PERIOD, **override}
    r = client.post("/api/v1/reconciliations", json=body)
    assert r.status_code == 422, r.text
    assert client.get("/api/v1/reconciliations").json()["total"] == 0


def test_run_is_audited(app, client, scenarios):
    body = reconcile(client, "FAC-11", actor_label="analyst-1").json()
    with app.state.sessionmaker() as s:
        audits = s.scalars(select(AuditEventRow).where(AuditEventRow.entity_type == "reconciliation")).all()
        links = s.scalars(
            select(ReconciliationEventRow).where(ReconciliationEventRow.reconciliation_id == body["reconciliation_id"])
        ).all()
    assert len(audits) == 1
    audit = audits[0]
    assert (audit.entity_id, audit.action, audit.actor_label) == (body["reconciliation_id"], "reconciliation_run", "analyst-1")
    assert audit.details["status"] == "NEEDS_REVIEW" and audit.details["variance_kg"] == "-80"
    assert len(links) == 5


def test_approving_exception_gives_new_snapshot_and_keeps_old(client, scenarios):
    first = reconcile(client, "FAC-15").json()
    assert first["status"] == "NEEDS_DATA"
    assert "REC-1506" in first["reasons"][0]
    excluded = first["events"]["excluded"]
    assert [e["source_record_id"] for e in excluded] == ["REC-1506"]
    assert excluded[0]["quantity_kg"] == "-10" and "OPEN" in excluded[0]["excluded_reason"]

    r = client.patch(
        f"/api/v1/quarantine/{excluded[0]['event_id']}/review",
        json={"review_status": "APPROVED", "actor_label": "analyst-1", "note": "Return to supplier, booked as negative shipment"},
    )
    assert r.status_code == 200, r.text

    second = reconcile(client, "FAC-15").json()
    assert second["reconciliation_id"] != first["reconciliation_id"]
    assert second["status"] == "WITHIN_TOLERANCE"
    # The -10 kg shipment is used exactly as recorded, not corrected (REC-004).
    assert (second["shipments_kg"], second["expected_closing_kg"], second["variance_kg"]) == ("-10", "290", "-10")
    assert [e["source_record_id"] for e in second["events"]["shipment"]] == ["REC-1506"]

    assert client.get(f"/api/v1/reconciliations/{first['reconciliation_id']}").json() == first
    assert client.get("/api/v1/reconciliations", params={"facility_id": "FAC-15"}).json()["total"] == 2
