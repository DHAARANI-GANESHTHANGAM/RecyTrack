"""Structured logs, request ids, and no secrets or payload values in logs (NFR-02, NFR-05)."""
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError

from app.database.tables import Base
from app.logging_config import JsonFormatter, TextFormatter, configure_logging
from app.main import create_app

PASSWORD = "Sup3r-Secret-Pa55"
PAYLOAD_VALUE = "Zebra-Polymer-7731"
HEADER = "source_record_id,facility_id,material_name,event_type,quantity,unit,event_timestamp,batch_id\n"


@pytest.fixture
def json_logs():
    """Every log line, formatted as the JSON handler writes it, captured from the root logger."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    root.removeHandler(handler)
    root.setLevel(old_level)


def test_json_lines_have_the_required_fields(json_logs):
    logging.getLogger("recytrack.test").warning("hello", extra={"run_id": "r-1", "received": 3})
    (line,) = [l for l in json_logs() if l["logger"] == "recytrack.test"]
    assert line["level"] == "WARNING" and line["message"] == "hello"
    assert (line["run_id"], line["received"]) == ("r-1", 3)
    assert line["ts"].endswith("Z")


def test_text_format_appends_extra_fields():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "done", None, None)
    record.run_id = "r-1"
    assert TextFormatter().format(record).endswith("INFO    x: done run_id=r-1")


def test_configure_logging_rejects_bad_values():
    with pytest.raises(ValueError, match="LOG_FORMAT"):
        configure_logging("xml")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        configure_logging("json", "LOUD")
    configure_logging("text", "INFO")
    configure_logging("text", "INFO")  # idempotent: still one handler of ours
    assert sum(h.get_name() == "recytrack" for h in logging.getLogger().handlers) == 1


def test_request_id_is_echoed_or_created(json_logs):
    with TestClient(create_app("sqlite://", init_attempts=1)) as client:
        given = client.get("/health", headers={"X-Request-ID": "abc-123"})
        created = client.get("/health")
        unsafe = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert given.headers["X-Request-ID"] == "abc-123"
    assert len(created.headers["X-Request-ID"]) == 32
    assert unsafe.headers["X-Request-ID"] != "bad id\nwith newline"

    requests = [l for l in json_logs() if l["logger"] == "recytrack.request"]
    first = requests[0]
    assert {k: first[k] for k in ("method", "path", "status", "request_id")} == {
        "method": "GET", "path": "/health", "status": 200, "request_id": "abc-123"
    }
    assert isinstance(first["duration_ms"], float)


def test_csv_import_logs_run_start_and_end_without_payload_values(json_logs):
    csv = (HEADER + f"SRC-1,FAC-01,{PAYLOAD_VALUE},RECEIPT,{PAYLOAD_VALUE},kg,2026-10-01T09:00:00Z,B-1\n").encode()
    with TestClient(create_app("sqlite://", init_attempts=1)) as client:
        Base.metadata.drop_all(client.app.state.engine)
        Base.metadata.create_all(client.app.state.engine)
        r = client.post("/api/v1/ingestion/csv", files={"file": ("x.csv", csv, "text/csv")}, headers={"X-Request-ID": "req-9"})
    assert r.status_code == 201
    lines = json_logs()
    finished = next(l for l in lines if l["message"] == "ingestion run finished")
    assert finished["request_id"] == "req-9"
    assert (finished["source_name"], finished["status"], finished["received"], finished["quarantined"]) == ("csv", "SUCCEEDED", 1, 1)
    assert "duration_ms" in finished
    assert any(l["message"] == "ingestion run started" for l in lines)
    assert PAYLOAD_VALUE not in json.dumps(lines)


def test_failed_database_call_logs_no_password(json_logs, caplog):
    # Nothing listens on port 1, so every database call fails.
    url = f"postgresql+psycopg://recytrack:{PASSWORD}@127.0.0.1:1/recytrack?connect_timeout=1"
    client = TestClient(create_app(url))  # no `with`: skip startup, which would retry the connection
    assert client.get("/health").status_code == 503
    r = client.get("/api/v1/ingestion/runs")
    assert r.status_code == 503
    assert PASSWORD not in r.text

    lines = json_logs()
    assert any(l["message"].startswith("Database error on GET /api/v1/ingestion/runs") for l in lines)
    assert PASSWORD not in json.dumps(lines)
    assert PASSWORD not in caplog.text


def test_database_error_text_with_row_values_is_not_logged(json_logs, caplog, monkeypatch):
    """SQLAlchemy errors quote SQL parameters, i.e. row values; only the class name is logged."""

    def failing_import(*args, **kwargs):
        raise DataError("INSERT INTO raw_records ...", {"raw_payload": PAYLOAD_VALUE}, Exception(PASSWORD))

    monkeypatch.setattr("app.api.routes.run_csv_ingestion", failing_import)
    with TestClient(create_app("sqlite://", init_attempts=1)) as client:
        r = client.post("/api/v1/ingestion/csv", files={"file": ("x.csv", HEADER.encode(), "text/csv")})
    assert r.status_code == 500
    assert PAYLOAD_VALUE not in r.text
    text = json.dumps(json_logs()) + caplog.text  # caplog's text includes any traceback
    assert "Database error on POST /api/v1/ingestion/csv: DataError" in text
    assert PAYLOAD_VALUE not in text and PASSWORD not in text
