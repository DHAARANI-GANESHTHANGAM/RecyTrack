import csv

import pytest

from app.ingestion.csv_reader import read_csv_bytes
from app.models import RunStatus, ValidationStatus
from app.pipeline import main, run_csv_ingestion
from app.store import InMemoryRepository

HEADER = "source_record_id,facility_id,material_name,event_type,quantity,unit,event_timestamp,batch_id\n"


def ingest(fixtures_dir, name, repo=None):
    repo = repo or InMemoryRepository()
    return run_csv_ingestion((fixtures_dir / name).read_bytes(), repo), repo


def test_valid_fixture_is_fully_accepted_and_raw_rows_preserved(fixtures_dir):
    result, repo = ingest(fixtures_dir, "valid_events.csv")
    s = result.run.summary()
    assert s["status"] == "SUCCEEDED"
    assert (s["received"], s["accepted"], s["quarantined"], s["flagged"], s["duplicates"]) == (10, 10, 0, 0, 0)
    assert len(repo.raw_records) == 10
    assert all(r.run_id == result.run.run_id for r in repo.raw_records)
    # Raw values are stored exactly as in the file, including odd whitespace.
    assert repo.raw_records[7].payload["material_name"] == "  recycled   resin "


def test_invalid_fixture_counts(fixtures_dir):
    result, repo = ingest(fixtures_dir, "invalid_events.csv")
    s = result.run.summary()
    assert s["received"] == 15
    assert (s["accepted"], s["quarantined"], s["flagged"], s["duplicates"]) == (2, 9, 3, 1)
    assert len(repo.raw_records) == 15  # nothing silently discarded


def test_labeled_expected_outcomes(fixtures_dir):
    """Every labeled row gets exactly the expected status and rule codes (SRS §11)."""
    with open(fixtures_dir / "expected_outcomes.csv", newline="") as f:
        expected_rows = list(csv.DictReader(f))

    by_fixture = {}
    for name in {row["fixture"] for row in expected_rows}:
        result, repo = ingest(fixtures_dir, name)
        raw_by_id = {r.raw_id: r for r in repo.raw_records}
        by_fixture[name] = {raw_by_id[e.raw_id].row_number: e for e in result.events}

    for row in expected_rows:
        event = by_fixture[row["fixture"]][int(row["row_number"])]
        expected_codes = set(filter(None, row["expected_rule_codes"].split(";")))
        assert event.validation_status.value == row["expected_status"], row
        assert {i.rule_code for i in event.issues} == expected_codes, row


def test_reimport_is_idempotent(fixtures_dir):
    repo = InMemoryRepository()
    first, _ = ingest(fixtures_dir, "valid_events.csv", repo)
    events_after_first = len(repo.events)

    second, _ = ingest(fixtures_dir, "valid_events.csv", repo)
    assert second.run.accepted_count == 0
    assert second.run.duplicate_count == 10
    assert len(repo.events) == events_after_first
    assert len(repo.raw_records) == 20  # raw input of both runs is still traceable
    assert second.run.run_id != first.run.run_id


def test_reimport_of_invalid_file_does_not_duplicate_exceptions(fixtures_dir):
    repo = InMemoryRepository()
    ingest(fixtures_dir, "invalid_events.csv", repo)
    events_after_first = len(repo.events)
    second, _ = ingest(fixtures_dir, "invalid_events.csv", repo)
    # The row without a source_record_id has no stable key, so it is re-evaluated.
    assert len(repo.events) == events_after_first + 1
    assert second.run.duplicate_count == 14  # every row with a stable key


def test_quarantined_record_is_traceable_to_row_and_run(fixtures_dir):
    result, repo = ingest(fixtures_dir, "invalid_events.csv")
    event = next(e for e in result.events if e.source_record_id == "SRC-2002")
    raw = next(r for r in repo.raw_records if r.raw_id == event.raw_id)
    assert raw.row_number == 3
    assert raw.run_id == result.run.run_id
    assert raw.payload["unit"] == "tons"
    assert event.issues[0].raw_value == "tons"


@pytest.mark.parametrize(
    "data, message_part",
    [
        (b"", "empty"),
        (b"foo,bar\n1,2\n", "missing columns"),
        (HEADER.replace("unit", "units").encode(), "unknown columns: units"),
        (b"\xff\xfe\x00bad", "UTF-8"),
    ],
)
def test_malformed_file_fails_run_with_actionable_error(data, message_part):
    result = run_csv_ingestion(data, InMemoryRepository())
    assert result.run.status is RunStatus.FAILED
    assert message_part in result.run.error_summary
    assert result.run.finished_at is not None


def test_header_with_bom_and_blank_lines_is_accepted():
    data = ("﻿" + HEADER + "SRC-1,FAC-01,Plastic film,RECEIPT,1,kg,2026-10-01T09:00:00Z,\n\n").encode()
    records = read_csv_bytes(data, "run", "csv")
    assert len(records) == 1


def test_cli_prints_summary(fixtures_dir, capsys):
    assert main([str(fixtures_dir / "invalid_events.csv")]) == 0
    out = capsys.readouterr().out
    assert '"quarantined": 9' in out
    assert "VAL-004(unit)" in out


def test_cli_reports_missing_file(capsys):
    assert main(["/nonexistent/file.csv"]) == 1
    assert "Cannot read" in capsys.readouterr().err
