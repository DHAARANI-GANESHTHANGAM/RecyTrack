"""Unit tests for the pure reconciliation engine (REC-001..REC-004)."""
import itertools
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.reconciliation.engine import (
    ReconciliationStatus,
    ReconEvent,
    describe_formula,
    describe_tolerance,
    reconcile,
)

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
_ids = itertools.count(1)


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=timezone.utc)


def ev(event_type, qty, when, status="ACCEPTED", reviews=(), facility="FAC-10", material="PLASTIC_FILM"):
    n = next(_ids)
    return ReconEvent(
        event_id=f"e{n}",
        facility_id=facility,
        material_code=material,
        event_type=event_type,
        quantity_kg=None if qty is None else Decimal(qty),
        event_timestamp=when,
        validation_status=status,
        review_statuses=tuple(reviews),
        source_record_id=f"SRC-{n}",
    )


def balanced(closing="280"):
    """Spec scenario: 1000 + 500 - 1200 - 20 = 280."""
    events = [
        ev("INVENTORY_COUNT", "1000", ts(1)),
        ev("RECEIPT", "500", ts(5)),
        ev("CONSUMPTION", "1200", ts(15)),
        ev("LOSS", "20", ts(20)),
    ]
    if closing is not None:
        events.append(ev("INVENTORY_COUNT", closing, ts(31, 23)))
    return events


def run(events, **kwargs):
    return reconcile(events, "FAC-10", "PLASTIC_FILM", START, END, **kwargs)


def roles(result) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for link in result.links:
        out.setdefault(link.role, []).append(link.event_id)
    return out


# ---------------------------------------------------------------- statuses


def test_balanced_is_within_tolerance():
    r = run(balanced())
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE
    assert (r.opening_stock_kg, r.receipts_kg, r.consumption_kg, r.losses_kg) == (1000, 500, 1200, 20)
    assert (r.expected_closing_kg, r.closing_stock_kg, r.variance_kg) == (280, 280, 0)
    assert (r.throughput_kg, r.tolerance_kg) == (1500, 15)
    assert r.reasons == ["|variance| 0 kg is within tolerance 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg)"]


def test_imbalanced_needs_review_and_says_it_is_not_proof():
    r = run(balanced(closing="200"))
    assert r.status is ReconciliationStatus.NEEDS_REVIEW
    assert r.variance_kg == Decimal("-80")
    assert r.reasons == [
        "|variance| 80 kg exceeds tolerance 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg). "
        "This is a flag for review, not proof of an error"
    ]


def test_boundary_is_inclusive():
    r = run(balanced(closing="265"))
    assert r.variance_kg == Decimal("-15")
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE


def test_just_past_the_boundary_needs_review():
    r = run(balanced(closing="264.99"))
    assert r.variance_kg == Decimal("-15.01")
    assert r.status is ReconciliationStatus.NEEDS_REVIEW


def test_missing_opening_count_needs_data_but_keeps_flows():
    events = [e for e in balanced() if e.event_timestamp != ts(1)]
    r = run(events)
    assert r.status is ReconciliationStatus.NEEDS_DATA
    assert r.reasons == ["No INVENTORY_COUNT at or before 2026-10-01T00:00:00Z"]
    assert r.opening_stock_kg is None and r.expected_closing_kg is None and r.tolerance_kg is None
    assert (r.receipts_kg, r.closing_stock_kg) == (500, 280)


def test_missing_closing_count_needs_data_with_expected_value():
    r = run(balanced(closing=None))
    assert r.status is ReconciliationStatus.NEEDS_DATA
    assert r.reasons == ["No INVENTORY_COUNT after 2026-10-01T00:00:00Z and at or before 2026-10-31T23:59:59Z"]
    assert (r.expected_closing_kg, r.tolerance_kg) == (280, 15)
    assert r.closing_stock_kg is None and r.variance_kg is None


def test_no_events_needs_data_with_both_reasons():
    r = run([])
    assert r.status is ReconciliationStatus.NEEDS_DATA
    assert len(r.reasons) == 2 and r.links == []


def test_count_after_period_end_is_not_the_closing_count():
    events = balanced(closing=None) + [ev("INVENTORY_COUNT", "280", datetime(2026, 11, 1, tzinfo=timezone.utc))]
    r = run(events)
    assert r.status is ReconciliationStatus.NEEDS_DATA and r.closing_stock_kg is None


# ---------------------------------------------------------------- accounting


def test_adjustments_keep_their_sign():
    events = balanced(closing="300") + [ev("INVENTORY_ADJUSTMENT", "30", ts(10)), ev("INVENTORY_ADJUSTMENT", "-10", ts(11))]
    r = run(events)
    assert r.adjustments_kg == Decimal("20")
    assert r.expected_closing_kg == Decimal("300")
    assert r.throughput_kg == Decimal("1500")  # adjustments are not throughput
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE


def test_production_and_shipment():
    events = [
        ev("INVENTORY_COUNT", "0", ts(1)),
        ev("PRODUCTION", "900", ts(12)),
        ev("SHIPMENT", "850", ts(22)),
        ev("INVENTORY_COUNT", "50", ts(31, 23)),
    ]
    r = run(events)
    assert (r.production_kg, r.shipments_kg, r.variance_kg, r.tolerance_kg) == (900, 850, 0, 9)


def test_intermediate_counts_are_not_flows():
    mid = ev("INVENTORY_COUNT", "999", ts(10))
    r = run(balanced() + [mid])
    assert r.variance_kg == 0 and r.status is ReconciliationStatus.WITHIN_TOLERANCE
    assert roles(r)["intermediate_count"] == [mid.event_id]


def test_events_at_count_timestamps():
    at_opening = ev("RECEIPT", "100", ts(1))  # already in the opening count
    at_closing = ev("RECEIPT", "50", ts(31, 23))  # included in the closing count
    r = run(balanced(closing="330") + [at_opening, at_closing])
    assert r.receipts_kg == Decimal("550")
    assert r.variance_kg == 0
    linked = {link.event_id for link in r.links}
    assert at_closing.event_id in linked and at_opening.event_id not in linked


def test_opening_count_may_be_before_period_start():
    early = [
        ev("INVENTORY_COUNT", "1000", datetime(2026, 9, 28, tzinfo=timezone.utc)),
        ev("RECEIPT", "100", datetime(2026, 9, 29, tzinfo=timezone.utc)),
    ]
    r = run(early + [ev("RECEIPT", "500", ts(5)), ev("INVENTORY_COUNT", "1600", ts(31, 23))])
    assert (r.opening_stock_kg, r.receipts_kg, r.variance_kg) == (1000, 600, 0)


def test_latest_opening_count_wins():
    events = [ev("INVENTORY_COUNT", "5", datetime(2026, 9, 1, tzinfo=timezone.utc))] + balanced()
    r = run(events)
    assert r.opening_stock_kg == 1000 and r.variance_kg == 0


def test_conflicting_closing_counts_need_data():
    events = balanced() + [ev("INVENTORY_COUNT", "290", ts(31, 23))]
    r = run(events)
    assert r.status is ReconciliationStatus.NEEDS_DATA
    assert r.closing_stock_kg is None and r.variance_kg is None
    assert r.reasons == ["Conflicting stock counts for the closing stock at 2026-10-31T23:00:00Z: 280 kg, 290 kg"]
    assert len(roles(r)["closing_count"]) == 2


def test_conflicting_opening_counts_need_data():
    events = balanced() + [ev("INVENTORY_COUNT", "900", ts(1))]
    r = run(events)
    assert r.status is ReconciliationStatus.NEEDS_DATA
    assert r.opening_stock_kg is None and r.expected_closing_kg is None
    assert r.receipts_kg == 500  # the window is still known from the timestamp


def test_identical_counts_at_one_timestamp_are_not_a_conflict():
    events = balanced() + [ev("INVENTORY_COUNT", "280.000", ts(31, 23))]
    r = run(events)
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE
    assert len(roles(r)["closing_count"]) == 2


def test_other_facilities_and_materials_are_ignored():
    noise = [ev("RECEIPT", "999", ts(5), facility="FAC-99"), ev("RECEIPT", "999", ts(5), material="RECYCLED_RESIN")]
    r = run(balanced() + noise)
    assert r.receipts_kg == 500 and len(r.links) == 5


# ---------------------------------------------------------------- which events count


def test_approved_flagged_event_is_included():
    flagged = ev("RECEIPT", "50", ts(6), status="FLAGGED", reviews=["APPROVED"])
    r = run(balanced(closing="330") + [flagged])
    assert r.receipts_kg == 550 and r.status is ReconciliationStatus.WITHIN_TOLERANCE
    assert flagged.event_id in roles(r)["receipt"]


def test_partly_approved_flagged_event_is_excluded():
    flagged = ev("RECEIPT", "50", ts(6), status="FLAGGED", reviews=["APPROVED", "OPEN"])
    r = run(balanced() + [flagged])
    assert r.receipts_kg == 500
    assert r.status is ReconciliationStatus.NEEDS_DATA


def test_rejected_event_is_excluded_and_listed():
    rejected = ev("RECEIPT", "50", ts(6), status="FLAGGED", reviews=["REJECTED"])
    r = run(balanced() + [rejected])
    assert r.receipts_kg == 500
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE  # rejected is resolved, not missing data
    link = next(link for link in r.links if link.event_id == rejected.event_id)
    assert link.role == "excluded" and "rejected" in link.excluded_reason


def test_rejected_quarantined_event_is_excluded_without_needs_data():
    q = ev("RECEIPT", "50", ts(6), status="QUARANTINED", reviews=["REJECTED"])
    r = run(balanced() + [q])
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE
    assert roles(r)["excluded"] == [q.event_id]


def test_approved_quarantined_event_is_still_excluded():
    q = ev("RECEIPT", "50", ts(6), status="QUARANTINED", reviews=["APPROVED"])
    r = run(balanced() + [q])
    assert r.receipts_kg == 500 and roles(r)["excluded"] == [q.event_id]


@pytest.mark.parametrize("status, review", [("FLAGGED", "OPEN"), ("FLAGGED", "NEEDS_INFO"), ("QUARANTINED", "OPEN")])
def test_unresolved_exception_needs_data(status, review):
    exc = ev("SHIPMENT", "-10", ts(25), status=status, reviews=[review])
    r = run(balanced() + [exc])
    assert r.status is ReconciliationStatus.NEEDS_DATA
    assert r.variance_kg == 0 and r.tolerance_kg == 15  # calculated values are still stored
    assert r.reasons[0].startswith("1 unresolved exception(s) for FAC-10 PLASTIC_FILM in the window")
    assert exc.source_record_id in r.reasons[0]
    link = next(link for link in r.links if link.event_id == exc.event_id)
    assert link.role == "excluded" and review in link.excluded_reason


def test_unresolved_exception_outside_the_window_does_not_block():
    before = ev("RECEIPT", "10", datetime(2026, 9, 15, tzinfo=timezone.utc), status="FLAGGED", reviews=["OPEN"])
    after = ev("RECEIPT", "10", datetime(2026, 11, 2, tzinfo=timezone.utc), status="FLAGGED", reviews=["OPEN"])
    r = run(balanced() + [before, after])
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE
    assert "excluded" not in roles(r)


def test_quarantined_count_is_not_used_as_closing():
    events = balanced(closing=None) + [ev("INVENTORY_COUNT", "280", ts(31, 23), status="QUARANTINED", reviews=["OPEN"])]
    r = run(events)
    assert r.closing_stock_kg is None
    assert r.status is ReconciliationStatus.NEEDS_DATA
    assert len(r.reasons) == 2  # missing closing count + unresolved exception


def test_approved_flagged_count_is_used():
    events = balanced(closing=None) + [ev("INVENTORY_COUNT", "280", ts(31, 23), status="FLAGGED", reviews=["APPROVED"])]
    assert run(events).status is ReconciliationStatus.WITHIN_TOLERANCE


# ---------------------------------------------------------------- tolerance and arithmetic


def test_custom_tolerance():
    loose = {"absolute_kg": Decimal("100"), "percent_of_throughput": Decimal("1.0")}
    r = run(balanced(closing="200"), tolerance=loose)
    assert (r.tolerance_kg, r.status) == (100, ReconciliationStatus.WITHIN_TOLERANCE)
    assert (r.tolerance_absolute_kg, r.tolerance_percent) == (Decimal("100"), Decimal("1.0"))

    pct = {"absolute_kg": Decimal("0"), "percent_of_throughput": Decimal("10")}
    assert run(balanced(closing="200"), tolerance=pct).tolerance_kg == Decimal("150")


def test_pound_conversion_stays_exact():
    lb_kg = Decimal("2205") * Decimal("0.45359237")
    events = [
        ev("INVENTORY_COUNT", "0", ts(1)),
        ev("RECEIPT", str(lb_kg), ts(6)),
        ev("CONSUMPTION", "1000", ts(12)),
        ev("INVENTORY_COUNT", "0", ts(31, 23)),
    ]
    r = run(events)
    assert r.variance_kg == Decimal("-0.17117585")
    assert r.tolerance_kg == Decimal("10.0017117585")
    assert r.status is ReconciliationStatus.WITHIN_TOLERANCE


def test_results_are_decimals():
    r = run(balanced(closing="264.99"))
    for name in ("opening_stock_kg", "receipts_kg", "expected_closing_kg", "variance_kg", "throughput_kg", "tolerance_kg"):
        assert isinstance(getattr(r, name), Decimal), name


def test_float_quantities_are_rejected():
    bad = ReconEvent("x", "FAC-10", "PLASTIC_FILM", "RECEIPT", 1.5, ts(5), "ACCEPTED")
    with pytest.raises(TypeError):
        run(balanced() + [bad])
    with pytest.raises(TypeError):
        run(balanced(), tolerance={"absolute_kg": 5.0, "percent_of_throughput": Decimal("1")})


def test_quantities_are_not_changed():
    events = balanced()
    before = [e.quantity_kg for e in events]
    run(events)
    assert [e.quantity_kg for e in events] == before


@pytest.mark.parametrize(
    "start, end, tolerance",
    [
        (END, START, None),
        (START, START, None),
        (START.replace(tzinfo=None), END, None),
        (START, END, {"absolute_kg": Decimal("-1"), "percent_of_throughput": Decimal("1")}),
    ],
)
def test_invalid_inputs_raise(start, end, tolerance):
    kwargs = {"tolerance": tolerance} if tolerance else {}
    with pytest.raises(ValueError):
        reconcile([], "FAC-10", "PLASTIC_FILM", start, end, **kwargs)


def test_formula_and_tolerance_text():
    r = run(balanced(closing="200"))
    formula = describe_formula(r)
    assert "1000 opening + 500 receipts + 0 production + 0 adjustments - 0 shipments - 20 losses - 1200 consumption = 280" in formula
    assert "variance_kg = 200 closing - 280 expected = -80" in formula
    assert "max of 5 kg absolute, 1.0% of throughput 1500 kg" in describe_tolerance(r)
    assert "unknown" in describe_formula(run(balanced(closing=None)))
