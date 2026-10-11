"""The measurement script (M8): result structure and 100% exact matches on the current fixtures.

The timing part is not run here; only its CSV generator is checked.
"""
import csv
import io
from decimal import Decimal

from scripts import measure


def test_labeled_quality_is_exact_on_every_set():
    quality = measure.labeled_quality()
    assert [q.name for q in quality] == ["valid_events.csv", "invalid_events.csv", "simulated_api", "Total"]
    for q in quality:
        assert q.exact == q.rows, q.mismatches
        assert q.detected == q.faulty
        assert q.false_positives == 0
        assert q.faulty + q.clean == q.rows
        assert q.expected_by_rule == q.found_by_rule

    total = quality[-1]
    assert (total.rows, total.faulty, total.detected, total.clean, total.false_positives) == (225, 33, 33, 192, 0)
    assert total.detection_rate == 1
    assert total.false_positive_rate == 0
    assert quality[0].detection_rate is None  # the clean file has no faulty rows


def test_compare_counts_misses_and_false_positives():
    labels = [
        {"row_number": "1", "expected_status": "QUARANTINED", "expected_rule_codes": "VAL-001"},
        {"row_number": "2", "expected_status": "ACCEPTED", "expected_rule_codes": ""},
        {"row_number": "3", "expected_status": "FLAGGED", "expected_rule_codes": "VAL-003;VAL-009"},
    ]
    actual = {
        1: measure.Outcome("ACCEPTED", frozenset()),  # missed
        2: measure.Outcome("FLAGGED", frozenset({"VAL-008"})),  # false positive
        3: measure.Outcome("FLAGGED", frozenset({"VAL-003", "VAL-009"})),
    }
    q = measure.compare("t", labels, actual)
    assert (q.rows, q.faulty, q.detected, q.clean, q.false_positives, q.exact) == (3, 2, 1, 1, 1, 1)
    assert q.detection_rate == Decimal("0.5")
    assert len(q.mismatches) == 2


def test_idempotency_second_import_creates_no_keyed_events():
    results = {i.name: i for i in measure.idempotency()}
    assert set(results) == {"valid_events.csv", "invalid_events.csv", "simulated_api"}
    assert all(i.passed for i in results.values())
    assert (results["valid_events.csv"].duplicates, results["valid_events.csv"].new_events) == (10, 0)
    assert (results["simulated_api"].duplicates, results["simulated_api"].new_events) == (200, 0)
    # The row without a source_record_id has no stable key and is re-evaluated; nothing else is new.
    invalid = results["invalid_events.csv"]
    assert (invalid.duplicates, invalid.new_events, invalid.new_events_without_key) == (14, 1, 1)


def test_reconciliation_scenarios_all_match():
    checks = measure.reconciliation()
    assert len(checks) == 7
    assert all(c.matches for c in checks), [c for c in checks if not c.matches]
    by_scenario = {c.scenario: c for c in checks}
    assert by_scenario["imbalanced"].status == "NEEDS_REVIEW"
    assert by_scenario["imbalanced"].variance_kg == Decimal("-80")
    assert by_scenario["missing_closing"].status == "NEEDS_DATA"


def test_report_and_exit_code(tmp_path, capsys):
    out = tmp_path / "results.md"
    assert measure.main(["--out", str(out)]) == 0
    report = out.read_text(encoding="utf-8")
    assert report.startswith("# Measured results")
    assert "| **Total** | 225 | 33 | 33 | 100.0% | 192 | 0 | 0.0% | 225 / 225 |" in report
    assert "**7 / 7**" in report
    assert "not** a real-world accuracy claim" in report
    assert "Not measured in this run" in report
    assert "All exact-match, idempotency and reconciliation checks passed" in report
    assert "# Measured results" in capsys.readouterr().out


def test_failures_are_listed():
    quality = measure.labeled_quality()
    quality[0].mismatches.append("valid_events.csv row 2: expected ACCEPTED [], got FLAGGED ['VAL-008']")
    assert measure.failures(quality, measure.idempotency(), []) == [
        "valid_events.csv row 2: expected ACCEPTED [], got FLAGGED ['VAL-008']"
    ]


def test_pct_never_rounds_to_a_perfect_score():
    assert measure.pct(Decimal(1)) == "100.0%"
    assert measure.pct(Decimal(0)) == "0.0%"
    assert measure.pct(Decimal(9999) / Decimal(10000)) == "99.9%"
    assert measure.pct(Decimal(1) / Decimal(10000)) == "<0.1%"
    assert measure.pct(None) == "n/a"


def test_perf_csv_is_seeded_and_has_the_contract_header():
    data = measure.perf_csv(rows=50)
    assert data == measure.perf_csv(rows=50)
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    assert len(rows) == 50
    assert list(rows[0]) == measure.PERF_HEADER.strip().split(",")
    assert len({r["source_record_id"] for r in rows}) == 50
