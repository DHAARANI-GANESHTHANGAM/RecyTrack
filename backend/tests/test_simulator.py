"""The simulated API source (M7): deterministic data, `since`, `limit` and fault injection."""
import time

import pytest
from fastapi.testclient import TestClient

from simulator.data import EVENT_COUNT, FACILITIES, generate_events
from simulator.main import create_app


@pytest.fixture
def sim():
    return TestClient(create_app("none"))


def test_health_is_labelled_simulated(sim):
    assert sim.get("/health").json() == {"status": "ok", "simulated": True}


def test_output_is_deterministic(sim):
    first = sim.get("/v1/events").json()
    second = TestClient(create_app("none")).get("/v1/events").json()
    assert first == second
    assert first["source"] == "simulated_api" and first["simulated"] is True
    assert len(first["items"]) == EVENT_COUNT


def test_data_covers_october_both_facilities_materials_and_types():
    events = generate_events()
    assert len(events) == 200
    assert {e.item["facility"] for e in events} == set(FACILITIES)
    assert all(e.at.year == 2026 and e.at.month == 10 for e in events)
    assert {e.item["type"] for e in events} >= {
        "RECEIPT", "PRODUCTION", "SHIPMENT", "LOSS", "INVENTORY_ADJUSTMENT", "INVENTORY_COUNT", "CONSUMPTION"
    }
    assert {e.item["material"] for e in events} >= {"Plastic film", "Recycled resin"}
    faulty = [e for e in events if e.expected_status != "ACCEPTED"]
    assert len(faulty) == 20  # about 10%
    assert {e.expected_rule_codes for e in faulty} == {"VAL-001", "VAL-003", "VAL-004", "VAL-005", "VAL-006", "VAL-009"}


def test_items_are_sorted_by_time_then_id():
    events = generate_events()
    keys = [(e.at, e.item["id"]) for e in events]
    assert keys == sorted(keys)


def test_since_is_exclusive(sim):
    items = sim.get("/v1/events").json()["items"]
    cut = items[49]["occurred_at"]
    after = sim.get("/v1/events", params={"since": cut}).json()
    assert all(i["id"] != items[49]["id"] for i in after["items"])
    assert after["items"][0] == items[50]
    assert len(after["items"]) == EVENT_COUNT - 50
    # An offset other than Z is understood too.
    assert sim.get("/v1/events", params={"since": "2026-10-01T02:00:00+02:00"}).json()["items"] == items


def test_since_without_offset_is_rejected(sim):
    r = sim.get("/v1/events", params={"since": "2026-10-01T00:00:00"})
    assert r.status_code == 422
    assert "timezone offset" in r.json()["detail"]


def test_limit_and_next_since(sim):
    page = sim.get("/v1/events", params={"limit": 10}).json()
    assert len(page["items"]) == 10
    assert page["next_since"] == page["items"][-1]["occurred_at"]
    nxt = sim.get("/v1/events", params={"limit": 10, "since": page["next_since"]}).json()
    assert nxt["items"][0] == sim.get("/v1/events").json()["items"][10]
    assert sim.get("/v1/events", params={"limit": 0}).status_code == 422
    assert sim.get("/v1/events", params={"limit": 1001}).status_code == 422


def test_failure_mode_always_500():
    sim = TestClient(create_app("always_500"))
    assert [sim.get("/v1/events").status_code for _ in range(3)] == [500, 500, 500]
    assert sim.get("/health").status_code == 200  # health checks are never affected


def test_failure_mode_flaky():
    sim = TestClient(create_app("flaky"))
    assert [sim.get("/v1/events").status_code for _ in range(4)] == [503, 503, 200, 200]


def test_failure_mode_slow():
    sim = TestClient(create_app("slow", slow_seconds=0.3))
    start = time.perf_counter()
    assert sim.get("/v1/events").status_code == 200
    assert time.perf_counter() - start >= 0.3


def test_failure_mode_from_environment(monkeypatch):
    monkeypatch.setenv("SIM_FAILURE_MODE", "always_500")
    assert TestClient(create_app()).get("/v1/events").status_code == 500
    monkeypatch.setenv("SIM_FAILURE_MODE", "sometimes")
    with pytest.raises(ValueError, match="not supported"):
        create_app()
