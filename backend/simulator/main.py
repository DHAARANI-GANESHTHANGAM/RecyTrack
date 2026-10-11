"""Simulated external event API (M7). Run with:  uvicorn simulator.main:app --port 8001

It runs as its own service so RecyTrack calls it over real HTTP, like an external system.
All data is synthetic. Field names deliberately differ from the CSV contract.

SIM_FAILURE_MODE injects faults for reliability testing:
  none (default)  normal responses
  always_500      every /v1/events request returns 500
  flaky           the first 2 /v1/events requests per process return 503, then OK
  slow            /v1/events sleeps SIM_SLOW_SECONDS (default 10 s, longer than the client timeout)
/health is never affected, so container health checks keep working.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query

from simulator.data import generate_events, iso_z

FAILURE_MODES = ("none", "always_500", "flaky", "slow")
FLAKY_FAILURES = 2
DEFAULT_SLOW_SECONDS = 10.0


def _parse_since(value: str) -> datetime:
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        raise HTTPException(
            422, f"since '{value}' must be ISO 8601 with a timezone offset, e.g. 2026-10-01T00:00:00Z."
        )
    return parsed


def create_app(failure_mode: str | None = None, slow_seconds: float | None = None) -> FastAPI:
    mode = (failure_mode or os.environ.get("SIM_FAILURE_MODE", "") or "none").strip().lower()
    if mode not in FAILURE_MODES:
        raise ValueError(f"SIM_FAILURE_MODE '{mode}' is not supported. Use one of: " + ", ".join(FAILURE_MODES))
    if slow_seconds is None:
        slow_seconds = float(os.environ.get("SIM_SLOW_SECONDS", DEFAULT_SLOW_SECONDS))

    app = FastAPI(
        title="RecyTrack simulated source (SIMULATED)",
        version="0.7.0",
        description="A simulated external event API for testing. All data is synthetic.",
    )
    app.state.failure_mode = mode
    app.state.events_requests = 0
    events = generate_events()

    @app.get("/health")
    def health():
        return {"status": "ok", "simulated": True}

    @app.get("/v1/events")
    async def list_events(
        since: str | None = Query(None, description="Only events after this time (exclusive). ISO 8601 with offset."),
        limit: int = Query(500, ge=1, le=1000),
    ):
        app.state.events_requests += 1
        if mode == "always_500":
            raise HTTPException(500, "Simulated failure (SIM_FAILURE_MODE=always_500).")
        if mode == "flaky" and app.state.events_requests <= FLAKY_FAILURES:
            raise HTTPException(503, "Simulated temporary outage (SIM_FAILURE_MODE=flaky).")
        if mode == "slow":
            await asyncio.sleep(slow_seconds)

        selected = events
        if since is not None:
            after = _parse_since(since)
            selected = [e for e in events if e.at > after]
        page = selected[:limit]
        return {
            "source": "simulated_api",
            "simulated": True,
            "items": [e.item for e in page],
            "next_since": iso_z(page[-1].at) if page else since,
        }

    return app


app = create_app()
