"""Material-flow reconciliation (SRS FR-10, FR-11, REC-001..REC-004).

Pure logic, no database: the caller passes in candidate events and stores the
result. All quantities are Decimal kilograms. They are summed exactly as given
and never changed, rounded or invented to make a balance work (REC-004).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Iterable, Mapping

from app.config import RECONCILIATION_TOLERANCE

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class ReconciliationStatus(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    NEEDS_REVIEW = "NEEDS_REVIEW"  # variance above tolerance: a review flag, not proof of an error
    NEEDS_DATA = "NEEDS_DATA"  # evidence is incomplete, so the balance cannot be trusted either way


# Event type -> role in the balance. INVENTORY_COUNT is not a flow; it sets the stock.
FLOW_ROLES = {
    "RECEIPT": "receipt",
    "PRODUCTION": "production",
    "INVENTORY_ADJUSTMENT": "adjustment",
    "SHIPMENT": "shipment",
    "LOSS": "loss",
    "CONSUMPTION": "consumption",
}
ROLES = (
    "opening_count",
    "closing_count",
    "intermediate_count",
    "receipt",
    "production",
    "adjustment",
    "shipment",
    "loss",
    "consumption",
    "excluded",
)
UNRESOLVED_REVIEW_STATUSES = frozenset({"OPEN", "NEEDS_INFO"})
EXCEPTION_STATUSES = frozenset({"FLAGGED", "QUARANTINED"})


@dataclass(frozen=True)
class ReconEvent:
    """The parts of a normalized event the balance needs."""

    event_id: str
    facility_id: str | None
    material_code: str | None
    event_type: str | None
    quantity_kg: Decimal | None
    event_timestamp: datetime | None
    validation_status: str
    review_statuses: tuple[str, ...] = ()  # one per validation issue
    source_record_id: str | None = None


@dataclass(frozen=True)
class EventLink:
    event_id: str
    role: str
    excluded_reason: str | None = None


@dataclass
class ReconciliationResult:
    facility_id: str
    material_code: str
    period_start: datetime
    period_end: datetime
    tolerance_absolute_kg: Decimal
    tolerance_percent: Decimal
    status: ReconciliationStatus
    reasons: list[str]
    links: list[EventLink]
    opening_stock_kg: Decimal | None = None
    receipts_kg: Decimal = ZERO
    production_kg: Decimal = ZERO
    adjustments_kg: Decimal = ZERO
    shipments_kg: Decimal = ZERO
    losses_kg: Decimal = ZERO
    consumption_kg: Decimal = ZERO
    closing_stock_kg: Decimal | None = None
    expected_closing_kg: Decimal | None = None
    variance_kg: Decimal | None = None
    throughput_kg: Decimal | None = None
    tolerance_kg: Decimal | None = None


def _review_statuses(event: ReconEvent) -> set[str]:
    # An exception with no recorded review is still waiting for one.
    return set(event.review_statuses) or {"OPEN"}


def exclusion_reason(event: ReconEvent) -> str | None:
    """None if the event counts in a balance, otherwise why it is left out (REC-001)."""
    if event.quantity_kg is None:
        return "No valid quantity in kg"
    status = event.validation_status
    if status == "ACCEPTED":
        return None
    reviews = _review_statuses(event)
    if status == "FLAGGED" and reviews == {"APPROVED"}:
        return None
    if "REJECTED" in reviews:
        return f"{status} and rejected by a reviewer"
    if status == "FLAGGED":
        return "FLAGGED and not approved by a reviewer (review status " + ", ".join(sorted(reviews)) + ")"
    if status == "QUARANTINED":
        return "QUARANTINED: not trusted for totals (review status " + ", ".join(sorted(reviews)) + ")"
    return f"{status} events are not counted"


def is_unresolved(event: ReconEvent) -> bool:
    """FLAGGED or QUARANTINED and still OPEN or NEEDS_INFO (REC-003)."""
    return event.validation_status in EXCEPTION_STATUSES and bool(_review_statuses(event) & UNRESOLVED_REVIEW_STATUSES)


def reconcile(
    events: Iterable[ReconEvent],
    facility_id: str,
    material_code: str,
    period_start: datetime,
    period_end: datetime,
    tolerance: Mapping[str, Decimal] = RECONCILIATION_TOLERANCE,
) -> ReconciliationResult:
    """Balance one facility + material over [period_start, period_end] (REC-001..REC-004)."""
    if period_start.tzinfo is None or period_end.tzinfo is None:
        raise ValueError("period_start and period_end must be timezone-aware")
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")
    absolute = _require_decimal(tolerance["absolute_kg"], "absolute_kg")
    percent = _require_decimal(tolerance["percent_of_throughput"], "percent_of_throughput")
    if absolute < 0 or percent < 0:
        raise ValueError("tolerances must not be negative")

    relevant = sorted(
        (
            e
            for e in events
            if e.facility_id == facility_id and e.material_code == material_code and e.event_timestamp is not None
        ),
        key=lambda e: (e.event_timestamp, e.event_id),
    )
    for e in relevant:
        if e.quantity_kg is not None:
            _require_decimal(e.quantity_kg, f"quantity_kg of event {e.event_id}")

    counts = [e for e in relevant if e.event_type == "INVENTORY_COUNT" and exclusion_reason(e) is None]
    data_reasons: list[str] = []
    opening = _latest(c for c in counts if c.event_timestamp <= period_start)
    closing = _latest(c for c in counts if period_start < c.event_timestamp <= period_end)
    opening_ts, opening_kg = _stock(
        opening, "opening", f"No INVENTORY_COUNT at or before {_iso(period_start)}", data_reasons
    )
    closing_ts, closing_kg = _stock(
        closing,
        "closing",
        f"No INVENTORY_COUNT after {_iso(period_start)} and at or before {_iso(period_end)}",
        data_reasons,
    )

    # A count reflects stock after all events at its timestamp, so the window is
    # (opening, closing]. Without a count, the period bound stands in for it.
    def in_window(ts: datetime) -> bool:
        after_start = ts > opening_ts if opening_ts is not None else ts >= period_start
        return after_start and ts <= (closing_ts if closing_ts is not None else period_end)

    links = [EventLink(c.event_id, "opening_count") for c in opening]
    links += [EventLink(c.event_id, "closing_count") for c in closing]
    stock_ids = {c.event_id for c in opening + closing}
    totals = {role: ZERO for role in FLOW_ROLES.values()}
    unresolved: list[ReconEvent] = []
    for e in relevant:
        if e.event_id in stock_ids or not in_window(e.event_timestamp):
            continue
        reason = exclusion_reason(e)
        if reason is None and e.event_type == "INVENTORY_COUNT":
            links.append(EventLink(e.event_id, "intermediate_count"))
        elif reason is None and e.event_type in FLOW_ROLES:
            role = FLOW_ROLES[e.event_type]
            totals[role] += e.quantity_kg
            links.append(EventLink(e.event_id, role))
        else:
            if is_unresolved(e):
                unresolved.append(e)
            links.append(EventLink(e.event_id, "excluded", reason or f"Event type {e.event_type} is not part of the balance"))
    if unresolved:
        data_reasons.append(
            f"{len(unresolved)} unresolved exception(s) for {facility_id} {material_code} in the window "
            "(review status OPEN or NEEDS_INFO): " + ", ".join(e.source_record_id or e.event_id for e in unresolved)
        )

    result = ReconciliationResult(
        facility_id=facility_id,
        material_code=material_code,
        period_start=period_start,
        period_end=period_end,
        tolerance_absolute_kg=absolute,
        tolerance_percent=percent,
        status=ReconciliationStatus.NEEDS_DATA,
        reasons=data_reasons,
        links=links,
        opening_stock_kg=opening_kg,
        receipts_kg=totals["receipt"],
        production_kg=totals["production"],
        adjustments_kg=totals["adjustment"],  # keeps its sign
        shipments_kg=totals["shipment"],
        losses_kg=totals["loss"],
        consumption_kg=totals["consumption"],
        closing_stock_kg=closing_kg,
    )
    if opening_kg is not None:
        result.expected_closing_kg = (
            opening_kg
            + result.receipts_kg
            + result.production_kg
            + result.adjustments_kg
            - result.shipments_kg
            - result.losses_kg
            - result.consumption_kg
        )
        result.throughput_kg = opening_kg + result.receipts_kg + result.production_kg
        result.tolerance_kg = max(absolute, result.throughput_kg * percent / HUNDRED)
        if closing_kg is not None:
            result.variance_kg = closing_kg - result.expected_closing_kg

    if result.variance_kg is not None:
        within = abs(result.variance_kg) <= result.tolerance_kg  # inclusive boundary (REC-002)
        if not data_reasons:
            result.status = ReconciliationStatus.WITHIN_TOLERANCE if within else ReconciliationStatus.NEEDS_REVIEW
        comparison = "is within" if within else "exceeds"
        sentence = (
            f"|variance| {_fmt(abs(result.variance_kg))} kg {comparison} tolerance {_fmt(result.tolerance_kg)} kg "
            f"({tolerance_basis(result)})"
        )
        if not within:
            sentence += ". This is a flag for review, not proof of an error"
        result.reasons.append(sentence)
    return result


def tolerance_basis(r) -> str:
    """'max of 5 kg absolute, 1.0% of throughput 1500 kg'. Works on results and stored rows."""
    throughput = (
        f"throughput {_fmt(r.throughput_kg)} kg" if r.throughput_kg is not None else "throughput (unknown without an opening count)"
    )
    return f"max of {_fmt(r.tolerance_absolute_kg)} kg absolute, {_fmt_percent(r.tolerance_percent)}% of {throughput}"


def describe_tolerance(r) -> str:
    total = _fmt(r.tolerance_kg) + " kg" if r.tolerance_kg is not None else "unknown"
    return f"tolerance_kg = {total} ({tolerance_basis(r)}); within tolerance when |variance_kg| <= tolerance_kg"


def describe_formula(r) -> str:
    """The REC-001 formula with this result's numbers filled in. Works on results and stored rows."""
    v = lambda x: "unknown" if x is None else _fmt(x)
    return "\n".join(
        [
            f"expected_closing_kg = {v(r.opening_stock_kg)} opening + {v(r.receipts_kg)} receipts"
            f" + {v(r.production_kg)} production + {v(r.adjustments_kg)} adjustments"
            f" - {v(r.shipments_kg)} shipments - {v(r.losses_kg)} losses - {v(r.consumption_kg)} consumption"
            f" = {v(r.expected_closing_kg)}",
            f"variance_kg = {v(r.closing_stock_kg)} closing - {v(r.expected_closing_kg)} expected = {v(r.variance_kg)}",
            f"throughput_kg = {v(r.opening_stock_kg)} opening + {v(r.receipts_kg)} receipts"
            f" + {v(r.production_kg)} production = {v(r.throughput_kg)}",
        ]
    )


def _latest(counts: Iterable[ReconEvent]) -> list[ReconEvent]:
    """All counts that share the latest timestamp (more than one may conflict)."""
    counts = list(counts)
    if not counts:
        return []
    ts = max(c.event_timestamp for c in counts)
    return [c for c in counts if c.event_timestamp == ts]


def _stock(
    counts: list[ReconEvent], label: str, missing: str, reasons: list[str]
) -> tuple[datetime | None, Decimal | None]:
    if not counts:
        reasons.append(missing)
        return None, None
    ts = counts[0].event_timestamp
    quantities = sorted({c.quantity_kg for c in counts})
    if len(quantities) > 1:
        reasons.append(
            f"Conflicting stock counts for the {label} stock at {_iso(ts)}: "
            + ", ".join(f"{_fmt(q)} kg" for q in quantities)
        )
        return ts, None
    return ts, quantities[0]


def _require_decimal(value, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, not {type(value).__name__}")
    return value


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fmt(value: Decimal) -> str:
    """1500.0 -> '1500', 15.010 -> '15.01', never exponent form."""
    if value == value.to_integral_value():
        return format(value.quantize(Decimal(1)), "f")
    return format(value.normalize(), "f")


def _fmt_percent(value: Decimal) -> str:
    """Always one decimal place or more (1 -> '1.0'), so stored and fresh results read the same."""
    text = _fmt(value)
    return text if "." in text else text + ".0"
