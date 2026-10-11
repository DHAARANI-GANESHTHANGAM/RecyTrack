"""Structured logging (NFR-02, NFR-05).

LOG_FORMAT=json|text (default text) and LOG_LEVEL (default INFO). JSON lines have
ts, level, logger and message, plus any `extra=` fields and the current request_id.

Never log row payloads, raw values, connection strings or passwords: log ids, counts,
statuses and exception class names instead.
"""
from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone

# Set by the request middleware so every log line inside a request carries its id.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_HANDLER_NAME = "recytrack"
# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


def _extras(record: logging.LogRecord) -> dict:
    fields = {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS and not k.startswith("_")}
    request_id = request_id_var.get()
    if request_id and "request_id" not in fields:
        fields["request_id"] = request_id
    return fields


def _timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": _timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info and record.exc_info[0] is not None:
            line["exc_type"] = record.exc_info[0].__name__
        return json.dumps(line, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = f"{_timestamp(record)} {record.levelname:<7} {record.name}: {record.getMessage()}"
        extras = _extras(record)
        if extras:
            text += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info and record.exc_info[0] is not None:
            text += f" exc_type={record.exc_info[0].__name__}"
        return text


def configure_logging(fmt: str | None = None, level: str | None = None) -> None:
    """Install one handler on the root logger. Safe to call more than once."""
    fmt = (fmt or os.environ.get("LOG_FORMAT", "") or "text").strip().lower()
    level = (level or os.environ.get("LOG_LEVEL", "") or "INFO").strip().upper()
    if fmt not in ("json", "text"):
        raise ValueError(f"LOG_FORMAT '{fmt}' is not supported. Use json or text.")
    if not isinstance(logging.getLevelName(level), int):
        raise ValueError(f"LOG_LEVEL '{level}' is not a logging level. Use DEBUG, INFO, WARNING or ERROR.")

    root = logging.getLogger()
    handler = next((h for h in root.handlers if h.get_name() == _HANDLER_NAME), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        root.addHandler(handler)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.setLevel(level)

    # Send uvicorn's own messages through the same handler and format. Its access log is
    # replaced by the request middleware's line, which also carries the request id.
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
