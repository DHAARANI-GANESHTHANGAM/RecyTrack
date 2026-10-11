"""VAL-010: source freshness, computed from ingestion runs (SRS §6, §9).

Pure logic: the caller passes the runs and `now`, so results are reproducible in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Mapping, Protocol


class FreshnessStatus(str, Enum):
    FRESH = "FRESH"  # last successful import is inside the window (the boundary counts as inside)
    STALE = "STALE"  # VAL-010: no successful import within the window
    NEVER_SUCCEEDED = "NEVER_SUCCEEDED"  # no successful import at all
    NO_WINDOW = "NO_WINDOW"  # a source seen in runs with no configured window; freshness is not judged


class RunLike(Protocol):
    source_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class SourceHealth:
    source_name: str
    last_run_at: datetime | None
    last_run_status: str | None
    last_success_at: datetime | None
    age_hours: float | None  # since the last success
    freshness_window_hours: int | None
    status: FreshnessStatus
    message: str


def _hours(value: float) -> str:
    return f"{value:.1f}"


def _status_value(status) -> str:
    return getattr(status, "value", status)


def _evaluate(source: str, runs: list[RunLike], window: int | None, now: datetime) -> SourceHealth:
    latest = max(runs, key=lambda r: r.started_at, default=None)
    successes = [r for r in runs if _status_value(r.status) == "SUCCEEDED"]
    last_success = max(successes, key=lambda r: r.started_at, default=None)
    success_at = (last_success.finished_at or last_success.started_at) if last_success else None
    last_status = _status_value(latest.status) if latest else None
    age = now - success_at if success_at else None
    age_hours = round(age.total_seconds() / 3600, 1) if age is not None else None
    window_text = f"window is {window} h" if window is not None else "no freshness window configured"

    if success_at is None:
        status = FreshnessStatus.NEVER_SUCCEEDED
        message = "No successful import yet" + (f" (latest run {last_status})" if last_status else "") + f"; {window_text}."
    elif window is None:
        status = FreshnessStatus.NO_WINDOW
        message = (
            f"Last successful import {_hours(age_hours)} h ago; {window_text}. "
            f"Add '{source}' to SOURCE_FRESHNESS_HOURS to check it."
        )
    elif age > timedelta(hours=window):
        status = FreshnessStatus.STALE
        message = f"No successful import in {_hours(age_hours)} h; {window_text}."
    else:
        status = FreshnessStatus.FRESH
        message = f"Last successful import {_hours(age_hours)} h ago; {window_text}."

    if latest is not None and last_success is not None and latest is not last_success and last_status == "FAILED":
        message += f" The latest run failed at {latest.started_at.isoformat()}."
    return SourceHealth(
        source_name=source,
        last_run_at=latest.started_at if latest else None,
        last_run_status=last_status,
        last_success_at=success_at,
        age_hours=age_hours,
        freshness_window_hours=window,
        status=status,
        message=message,
    )


def source_health(runs: Iterable[RunLike], freshness: Mapping[str, int], now: datetime) -> list[SourceHealth]:
    """One entry per configured source plus any other source seen in runs, sorted by name."""
    by_source: dict[str, list[RunLike]] = {name: [] for name in freshness}
    for run in runs:
        by_source.setdefault(run.source_name, []).append(run)
    return [_evaluate(name, by_source[name], freshness.get(name), now) for name in sorted(by_source)]
