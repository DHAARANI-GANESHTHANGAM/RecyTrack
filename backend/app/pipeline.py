"""Ingestion pipeline: raw -> normalize -> validate -> classify -> store (SRS §3.1).

Usage:  python -m app.pipeline path/to/file.csv [more.csv ...]
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

from app.ingestion.api_records import SIMULATED_SOURCE, records_from_api_items
from app.ingestion.csv_reader import CsvFormatError, read_csv_bytes
from app.models import (
    IngestionRun,
    NormalizedEvent,
    RawRecord,
    RunStatus,
    Severity,
    ValidationIssue,
    ValidationStatus,
    utc_now,
)
from app.normalization.normalize import clean_text, normalize_record
from app.store import InMemoryRepository, Repository
from app.validation.rules import status_for, validate_record

log = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    run: IngestionRun
    events: list[NormalizedEvent] = field(default_factory=list)


def _start_run(repo: Repository, source_name: str, file_name: str | None, started_at: datetime | None = None) -> IngestionRun:
    run = IngestionRun(source_name=source_name, file_name=file_name)
    if started_at is not None:
        run.started_at = started_at
    repo.save_run(run)
    log.info("ingestion run started", extra={"run_id": run.run_id, "source_name": source_name})
    return run


def _finish_run(repo: Repository, run: IngestionRun, status: RunStatus, error_summary: str | None = None) -> None:
    run.status = status
    run.error_summary = error_summary
    run.finished_at = utc_now()
    repo.save_run(run)
    # Counts and ids only: never row values or the error text, which can quote input.
    log.info(
        "ingestion run finished",
        extra={
            "run_id": run.run_id,
            "source_name": run.source_name,
            "status": run.status.value,
            "received": run.received_count,
            "accepted": run.accepted_count,
            "quarantined": run.quarantined_count,
            "flagged": run.flagged_count,
            "duplicates": run.duplicate_count,
            "duration_ms": round((run.finished_at - run.started_at).total_seconds() * 1000),
        },
    )


def process_raw_records(raw_records: list[RawRecord], run: IngestionRun, repo: Repository) -> list[NormalizedEvent]:
    """Normalize -> duplicate check -> validate -> store, updating the run's counts.

    Shared by every source. Duplicate keys are (run.source_name, source_record_id).
    """
    source_name = run.source_name
    events: list[NormalizedEvent] = []
    # Hashes already stored per stable key, kept up to date as this run adds events.
    known = repo.find_hashes_for_keys(
        {(source_name, key_id) for r in raw_records if (key_id := clean_text(r.payload.get("source_record_id")))}
    )

    for raw in raw_records:
        repo.save_raw(raw)  # raw data is always kept, whatever happens next
        run.received_count += 1
        event = normalize_record(raw)

        # VAL-007 / VAL-009: stable key = (source_name, source_record_id).
        if event.source_record_id:
            known_hashes = known.get((source_name, event.source_record_id), set())
            if raw.payload_hash in known_hashes:
                event.validation_status = ValidationStatus.DUPLICATE
                event.issues = [
                    ValidationIssue(
                        "VAL-007",
                        "source_record_id",
                        f"Record {event.source_record_id} was already imported with identical values; no new event created.",
                        Severity.WARNING,
                        event.source_record_id,
                    )
                ]
                run.duplicate_count += 1
                events.append(event)
                continue
        else:
            known_hashes = set()

        issues = validate_record(raw, event)
        if known_hashes:
            issues.append(
                ValidationIssue(
                    "VAL-009",
                    "source_record_id",
                    f"Record {event.source_record_id} was already imported with different values; "
                    "both versions are kept for review.",
                    Severity.WARNING,
                    event.source_record_id,
                )
            )
        event.issues = issues
        event.validation_status = status_for(issues)
        repo.save_event(event, raw.payload_hash)
        if event.source_record_id:
            known.setdefault((source_name, event.source_record_id), set()).add(raw.payload_hash)
        events.append(event)

        if event.validation_status is ValidationStatus.ACCEPTED:
            run.accepted_count += 1
        elif event.validation_status is ValidationStatus.FLAGGED:
            run.flagged_count += 1
        else:
            run.quarantined_count += 1
    return events


def run_csv_ingestion(
    data: bytes, repo: Repository, source_name: str = "csv", file_name: str | None = None
) -> IngestionResult:
    """Import one CSV payload. Whole-file problems mark the run FAILED instead of raising."""
    run = _start_run(repo, source_name, file_name)
    result = IngestionResult(run=run)

    try:
        raw_records = read_csv_bytes(data, run.run_id, source_name)
    except CsvFormatError as exc:
        _finish_run(repo, run, RunStatus.FAILED, str(exc))
        return result

    result.events = process_raw_records(raw_records, run, repo)
    _finish_run(repo, run, RunStatus.SUCCEEDED)
    return result


def run_api_ingestion(
    items: list[dict],
    repo: Repository,
    source_name: str = SIMULATED_SOURCE,
    file_name: str | None = None,
    started_at: datetime | None = None,
) -> IngestionResult:
    """Import items already fetched from an API source, with the same counts and run record as CSV.

    `started_at` lets the run include the time spent fetching.
    """
    run = _start_run(repo, source_name, file_name, started_at)
    result = IngestionResult(run=run)
    raw_records = records_from_api_items(items, run.run_id, source_name)
    result.events = process_raw_records(raw_records, run, repo)
    _finish_run(repo, run, RunStatus.SUCCEEDED)
    return result


def record_failed_run(
    repo: Repository,
    error_summary: str,
    source_name: str = SIMULATED_SOURCE,
    file_name: str | None = None,
    started_at: datetime | None = None,
) -> IngestionRun:
    """Save a FAILED run for a source that could not be read, so the failure stays visible."""
    run = _start_run(repo, source_name, file_name, started_at)
    _finish_run(repo, run, RunStatus.FAILED, error_summary)
    return run


def _print_result(path: str, result: IngestionResult) -> None:
    print(f"== {path}")
    print(json.dumps(result.run.summary(), indent=2))
    for event in result.events:
        if event.validation_status is ValidationStatus.ACCEPTED:
            continue
        codes = ", ".join(f"{i.rule_code}({i.field_name or 'row'})" for i in event.issues)
        print(f"  {event.validation_status.value:<11} {event.source_record_id or '<no id>':<10} {codes}")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    repo = InMemoryRepository()
    failed = False
    for path in argv:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            print(f"Cannot read {path}: {exc.strerror}", file=sys.stderr)
            failed = True
            continue
        result = run_csv_ingestion(data, repo, file_name=os.path.basename(path))
        failed |= result.run.status is RunStatus.FAILED
        _print_result(path, result)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
