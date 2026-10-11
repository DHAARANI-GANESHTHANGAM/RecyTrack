"""VAL-010 source freshness: the pure function and GET /api/v1/sources/health."""
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_now
from app.database.tables import Base, IngestionRunRow
from app.main import create_app
from app.validation.freshness import FreshnessStatus, source_health

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
WINDOWS = {"csv": 168, "simulated_api": 24}


@dataclass
class Run:
    source_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def health(runs, windows=WINDOWS):
    return {h.source_name: h for h in source_health(runs, windows, NOW)}


def test_fresh():
    h = health([Run("simulated_api", "SUCCEEDED", ago(2.05), ago(2))])["simulated_api"]
    assert h.status is FreshnessStatus.FRESH
    assert (h.age_hours, h.freshness_window_hours, h.last_run_status) == (2.0, 24, "SUCCEEDED")
    assert h.last_success_at == ago(2)  # the run's finish time
    assert h.message == "Last successful import 2.0 h ago; window is 24 h."


def test_stale():
    h = health([Run("simulated_api", "SUCCEEDED", ago(30.5), ago(30.5))])["simulated_api"]
    assert h.status is FreshnessStatus.STALE
    assert h.message == "No successful import in 30.5 h; window is 24 h."


def test_never_succeeded():
    result = health([Run("simulated_api", "FAILED", ago(1), ago(1))])
    assert result["simulated_api"].status is FreshnessStatus.NEVER_SUCCEEDED
    assert result["simulated_api"].last_run_status == "FAILED"
    assert result["simulated_api"].message == "No successful import yet (latest run FAILED); window is 24 h."
    # A configured source with no runs at all is listed too.
    assert result["csv"].status is FreshnessStatus.NEVER_SUCCEEDED
    assert result["csv"].last_run_at is None
    assert result["csv"].message == "No successful import yet; window is 168 h."


def test_failure_inside_the_window_stays_fresh_and_shows_the_failure():
    h = health(
        [
            Run("simulated_api", "SUCCEEDED", ago(5), ago(5)),
            Run("simulated_api", "FAILED", ago(1), ago(1)),
        ]
    )["simulated_api"]
    assert h.status is FreshnessStatus.FRESH
    assert h.last_run_status == "FAILED"
    assert h.last_run_at == ago(1)
    assert h.last_success_at == ago(5)
    assert h.message.endswith("The latest run failed; see its error on the Ingestion page.")
    # The failure time is a separate field, not raw ISO text inside the message.
    assert "2026-" not in h.message


def test_boundary_exactly_at_the_window_is_fresh():
    at_edge = health([Run("simulated_api", "SUCCEEDED", ago(24), ago(24))])["simulated_api"]
    assert at_edge.status is FreshnessStatus.FRESH
    just_over = NOW - timedelta(hours=24, microseconds=1)
    assert health([Run("simulated_api", "SUCCEEDED", just_over, just_over)])["simulated_api"].status is FreshnessStatus.STALE


def test_unknown_source_is_listed_without_a_window():
    result = health([Run("partner_feed", "SUCCEEDED", ago(400), ago(400))])
    assert sorted(result) == ["csv", "partner_feed", "simulated_api"]
    h = result["partner_feed"]
    assert h.status is FreshnessStatus.NO_WINDOW
    assert h.freshness_window_hours is None
    assert "Add 'partner_feed' to SOURCE_FRESHNESS_HOURS" in h.message


def test_latest_success_wins_regardless_of_order():
    h = health(
        [
            Run("csv", "SUCCEEDED", ago(1), ago(1)),
            Run("csv", "SUCCEEDED", ago(500), ago(500)),
        ]
    )["csv"]
    assert h.status is FreshnessStatus.FRESH and h.age_hours == 1.0


# ---------------------------------------------------------------- API


@pytest.fixture
def client():
    app = create_app(os.environ.get("TEST_DATABASE_URL", "sqlite://"), init_attempts=1)
    Base.metadata.drop_all(app.state.engine)
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as c:
        yield c


def add_run(client, source_name, status, started_at):
    with client.app.state.sessionmaker() as s:
        s.add(IngestionRunRow(run_id=str(uuid.uuid4()), source_name=source_name,
                              started_at=started_at, finished_at=started_at, status=status))
        s.commit()


def test_sources_health_endpoint(client):
    add_run(client, "csv", "SUCCEEDED", ago(200))
    add_run(client, "simulated_api", "SUCCEEDED", ago(3))
    add_run(client, "simulated_api", "FAILED", ago(1))
    body = {h["source_name"]: h for h in client.get("/api/v1/sources/health").json()}
    assert body["csv"]["status"] == "STALE"
    assert body["csv"]["message"] == "No successful import in 200.0 h; window is 168 h."
    assert body["simulated_api"]["status"] == "FRESH"
    assert body["simulated_api"]["last_run_status"] == "FAILED"
    assert body["simulated_api"]["age_hours"] == 3.0
    assert client.get("/api/v1/metrics/quality").json()["sources_stale"] == 1


def test_sources_health_on_an_empty_database(client):
    body = client.get("/api/v1/sources/health").json()
    assert [(h["source_name"], h["status"]) for h in body] == [("csv", "NEVER_SUCCEEDED"), ("simulated_api", "NEVER_SUCCEEDED")]
    assert client.get("/api/v1/metrics/quality").json()["sources_stale"] == 0
