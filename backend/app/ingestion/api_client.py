"""HTTP client for the simulated API source with bounded retries (NFR-02).

Retries are safe: reading events is idempotent, and so is importing them (VAL-007).
Only connection errors, timeouts and 5xx responses are retried; a 4xx means the request
itself is wrong and is reported at once. Response bodies are never logged.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)

EVENTS_PATH = "/v1/events"
PAGE_LIMIT = 1000  # the source's maximum page size


class SourceError(Exception):
    """The source could not provide events. The message tells the user what to check."""


class SourceUnavailableError(SourceError):
    """Every attempt failed with a connection error, a timeout or a 5xx response."""


class SourceRejectedError(SourceError):
    """The source answered 4xx. Retrying the same request would not help."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def safe_url(url: str) -> str:
    """The URL without any user:password part, for messages and logs."""
    parts = urlsplit(url)
    if parts.username is None and parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def _error_detail(response: httpx.Response) -> str:
    """The source's own error message (FastAPI `detail`), shortened."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
    text = str(detail) if detail else response.reason_phrase or "no error message"
    return text[:300]


def _parse_page(response: httpx.Response, where: str) -> tuple[list[dict], str | None]:
    try:
        # Decimals keep numbers exactly as sent if a source uses JSON numbers.
        body = json.loads(response.text, parse_float=Decimal)
    except ValueError:
        body = None
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise SourceError(
            f"Simulated source at {where} returned an unexpected response (expected JSON with an 'items' list of "
            "objects). Check that SIMULATED_SOURCE_URL points to the simulator."
        )
    next_since = body.get("next_since")
    return items, next_since if isinstance(next_since, str) else None


def _get_with_retries(
    client: httpx.Client,
    params: dict[str, str | int],
    where: str,
    attempts: int,
    backoff_s: float,
    sleep: Callable[[float], None],
) -> httpx.Response:
    last_error = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(EVENTS_PATH, params=params)
        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.TransportError as exc:
            last_error = f"connection error ({exc.__class__.__name__})"
        else:
            if response.status_code < 400:
                return response
            if response.status_code < 500:
                raise SourceRejectedError(
                    f"Simulated source at {where} rejected the request with HTTP {response.status_code}: "
                    f"{_error_detail(response)}. This is not retried; check the request (e.g. 'since').",
                    response.status_code,
                )
            last_error = f"HTTP {response.status_code}"

        if attempt < attempts:
            delay = backoff_s * 2 ** (attempt - 1)
            log.warning(
                "source request failed; retrying",
                extra={
                    "source_url": where,
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "reason": last_error,
                    "retry_delay_s": delay,
                },
            )
            sleep(delay)

    raise SourceUnavailableError(
        f"Simulated source at {where} unreachable after {attempts} attempt{'s' if attempts != 1 else ''} "
        f"(last error: {last_error}). Check that the simulator is running."
    )


def fetch_simulated_events(
    base_url: str,
    since: datetime | None,
    *,
    attempts: int = 3,
    backoff_s: float = 0.5,
    timeout_s: float = 5.0,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """Every event after `since` (exclusive), in the source's order.

    Each page request makes at most `attempts` tries, waiting backoff_s * 2**n between them.
    Raises SourceUnavailableError after the last failed try and SourceRejectedError on a 4xx.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    where = safe_url(base_url.rstrip("/"))
    items: list[dict] = []
    cursor = since.isoformat() if since is not None else None
    with httpx.Client(base_url=base_url, timeout=timeout_s, transport=transport) as client:
        while True:
            params: dict[str, str | int] = {"limit": PAGE_LIMIT}
            if cursor is not None:
                params["since"] = cursor
            response = _get_with_retries(client, params, where, attempts, backoff_s, sleep)
            page, next_since = _parse_page(response, where)
            items.extend(page)
            if len(page) < PAGE_LIMIT or not next_since or next_since == cursor:
                return items
            cursor = next_since
