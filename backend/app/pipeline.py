"""Ingestion pipeline: raw -> normalize -> validate -> classify -> store (SRS §3.1).

Usage:  python -m app.pipeline path/to/file.csv [more.csv ...]
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field

from app.ingestion.csv_reader import CsvFormatError, read_csv_bytes
from app.models import (
    IngestionRun,
    NormalizedEvent,
    RunStatus,
    Severity,
    ValidationIssue,
    ValidationStatus,
    utc_now,
)
from app.normalization.normalize import clean_text, normalize_record
from app.store import InMemoryRepository, Repository
from app.validation.rules import status_for, validate_record


@dataclass
class IngestionResult:
    run: IngestionRun
    events: list[NormalizedEvent] = field(default_factory=list)


def run_csv_ingestion(
    data: bytes, repo: Repository, source_name: str = "csv", file_name: str | None = None
) -> IngestionResult:
    """Import one CSV payload. Whole-file problems mark the run FAILED instead of raising."""
    run = IngestionRun(source_name=source_name, file_name=file_name)
    repo.save_run(run)
    result = IngestionResult(run=run)

    try:
        raw_records = read_csv_bytes(data, run.run_id, source_name)
    except CsvFormatError as exc:
        run.status = RunStatus.FAILED
        run.error_summary = str(exc)
        run.finished_at = utc_now()
        repo.save_run(run)
        return result

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
                result.events.append(event)
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
        result.events.append(event)

        if event.validation_status is ValidationStatus.ACCEPTED:
            run.accepted_count += 1
        elif event.validation_status is ValidationStatus.FLAGGED:
            run.flagged_count += 1
        else:
            run.quarantined_count += 1

    run.status = RunStatus.SUCCEEDED
    run.finished_at = utc_now()
    repo.save_run(run)
    return result


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
