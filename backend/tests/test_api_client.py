"""Bounded retries for the simulated source client (NFR-02). No network: httpx.MockTransport."""
import logging
from datetime import datetime, timezone

import httpx
import pytest

from app.ingestion.api_client import (
    SourceError,
    SourceRejectedError,
    SourceUnavailableError,
    fetch_simulated_events,
    safe_url,
)
from simulator.main import create_app
from tests.conftest import simulator_transport

URL = "http://simulator:8001"
PAGE = {"source": "simulated_api", "simulated": True, "items": [{"id": "SIM-1"}], "next_since": "2026-10-01T06:00:00Z"}


def scripted(*responses):
    """A transport that answers with the given responses (or raises the given exceptions) in order."""
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        answer = responses[min(len(calls), len(responses)) - 1]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle), calls


def fetch(transport, **kwargs):
    kwargs.setdefault("sleep", lambda s: None)
    return fetch_simulated_events(URL, None, transport=transport, **kwargs)


def test_success():
    transport, calls = scripted((200, PAGE))
    assert fetch(transport) == [{"id": "SIM-1"}]
    assert len(calls) == 1
    assert calls[0].url.path == "/v1/events"
    assert "since" not in calls[0].url.params


def test_since_is_sent_with_its_offset():
    transport, calls = scripted((200, PAGE))
    fetch_simulated_events(URL, datetime(2026, 10, 1, 6, tzinfo=timezone.utc), transport=transport)
    assert calls[0].url.params["since"] == "2026-10-01T06:00:00+00:00"


def test_flaky_source_succeeds_on_third_attempt_and_logs_retries(caplog):
    transport, calls = scripted((503, {"detail": "down"}), (503, {"detail": "down"}), (200, PAGE))
    with caplog.at_level(logging.WARNING, logger="app.ingestion.api_client"):
        assert fetch(transport) == [{"id": "SIM-1"}]
    assert len(calls) == 3
    retries = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [(r.attempt, r.reason, r.retry_delay_s) for r in retries] == [(1, "HTTP 503", 0.5), (2, "HTTP 503", 1.0)]


def test_flaky_simulator_end_to_end():
    transport = simulator_transport(create_app("flaky"))
    assert len(fetch(transport)) == 200


def test_always_500_raises_after_exactly_three_attempts():
    transport, calls = scripted((500, {"detail": "boom"}))
    with pytest.raises(SourceUnavailableError) as err:
        fetch(transport)
    assert len(calls) == 3
    assert str(err.value) == (
        "Simulated source at http://simulator:8001 unreachable after 3 attempts (last error: HTTP 500). "
        "Check that the simulator is running."
    )


def test_timeout_is_retried():
    transport, calls = scripted(httpx.ReadTimeout("slow"), (200, PAGE))
    assert fetch(transport) == [{"id": "SIM-1"}]
    assert len(calls) == 2


def test_repeated_timeouts_name_the_last_error():
    transport, calls = scripted(httpx.ReadTimeout("slow"))
    with pytest.raises(SourceUnavailableError, match=r"after 3 attempts \(last error: timeout\)"):
        fetch(transport)
    assert len(calls) == 3


def test_connection_error_is_retried():
    transport, calls = scripted(httpx.ConnectError("refused"))
    with pytest.raises(SourceUnavailableError, match="connection error"):
        fetch(transport, attempts=2)
    assert len(calls) == 2


def test_404_is_not_retried():
    transport, calls = scripted((404, {"detail": "Not Found"}))
    with pytest.raises(SourceRejectedError) as err:
        fetch(transport)
    assert len(calls) == 1
    assert err.value.status_code == 404
    assert "HTTP 404: Not Found" in str(err.value)


def test_422_carries_the_source_message():
    transport = simulator_transport(create_app("none"))
    with pytest.raises(SourceRejectedError, match="timezone offset"):
        fetch_simulated_events(URL, datetime(2026, 10, 1), transport=transport)  # naive: the source rejects it


def test_backoff_delays_are_exponential():
    delays = []
    transport, _ = scripted((503, {}))
    with pytest.raises(SourceUnavailableError):
        fetch(transport, attempts=4, backoff_s=0.25, sleep=delays.append)
    assert delays == [0.25, 0.5, 1.0]  # backoff_s * 2**n, none after the last attempt


def test_unexpected_body_is_an_error_without_retries():
    transport, calls = scripted((200, {"rows": []}))
    with pytest.raises(SourceError, match="unexpected response"):
        fetch(transport)
    assert len(calls) == 1


def test_pages_are_followed_until_a_short_page(monkeypatch):
    monkeypatch.setattr("app.ingestion.api_client.PAGE_LIMIT", 50)
    transport = simulator_transport(create_app("none"))
    items = fetch(transport)
    assert len(items) == 200
    assert len({(i["id"], i.get("qty")) for i in items}) == 200


def test_credentials_never_appear_in_messages():
    assert safe_url("http://user:secret@simulator:8001/x") == "http://simulator:8001/x"
    transport, _ = scripted((500, {}))
    with pytest.raises(SourceUnavailableError) as err:
        fetch_simulated_events("http://user:secret@simulator:8001", None, transport=transport, sleep=lambda s: None)
    assert "secret" not in str(err.value)
