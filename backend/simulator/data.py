"""Deterministic synthetic events for the simulated API source (SRS §1.4, §5.3).

A fixed seed produces the same 200 events every time: October 2026, facilities FAC-20 and FAC-21,
both materials, every event type. About 10% are deliberately faulty. Each event carries the outcome
the pipeline should give it, so `data/fixtures/simulated_expected_outcomes.csv` is written from the
generator's intent, not from the pipeline's output.

Regenerate the fixture:  python -m simulator.data ../data/fixtures/simulated_expected_outcomes.csv
"""
from __future__ import annotations

import csv
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

SEED = 20261001
EVENT_COUNT = 200
FACILITIES = ("FAC-20", "FAC-21")
# Names as an external system might send them; all are known aliases (app.config.MATERIAL_ALIASES).
MATERIALS = ("Plastic film", "LDPE film", "Recycled resin", "PCR resin")
# Kept here rather than imported from app.config so the simulator stays a separate service.
EVENT_TYPES = (
    "RECEIPT",
    "PRODUCTION",
    "SHIPMENT",
    "LOSS",
    "INVENTORY_ADJUSTMENT",
    "INVENTORY_COUNT",
    "CONSUMPTION",
)
START = datetime(2026, 10, 1, tzinfo=timezone.utc)

# Fault kind -> (expected status, expected rule codes, description).
FAULTS = {
    "missing_qty": ("QUARANTINED", "VAL-001", "Missing qty"),
    "unknown_unit": ("QUARANTINED", "VAL-004", "Unknown unit"),
    "bad_timestamp": ("QUARANTINED", "VAL-005", "Bad timestamp"),
    "unknown_type": ("QUARANTINED", "VAL-006", "Unknown event type"),
    "negative_shipment": ("FLAGGED", "VAL-003", "Negative shipment"),
    "conflicting_qty": ("FLAGGED", "VAL-009", "Same id as an earlier event with a different qty"),
}
FAULT_RATE = 0.10
BAD_TIMESTAMPS = ("2026-10-32T06:00:00Z", "2026-10-05 06:00", "05/10/2026 06:00")


@dataclass
class SimEvent:
    """One item of the response plus what the generator intended."""

    at: datetime  # real time, used for `since` filtering and ordering even when the sent string is bad
    seq: int  # generation order; breaks ties so the order is always the same
    item: dict[str, str] = field(default_factory=dict)
    expected_status: str = "ACCEPTED"
    expected_rule_codes: str = ""
    description: str = ""


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_event(rng: random.Random, n: int) -> SimEvent:
    at = START + timedelta(hours=3 * n, minutes=rng.randrange(0, 150))
    event_type = EVENT_TYPES[n % len(EVENT_TYPES)]  # every type appears
    qty = f"{rng.randint(50, 5000)}.{rng.randint(0, 9)}"
    if event_type == "INVENTORY_ADJUSTMENT" and rng.random() < 0.5:
        qty = "-" + qty  # adjustments may be negative; this is valid
    item = {
        "id": f"SIM-{n + 1:04d}",
        "facility": FACILITIES[n % 2],
        "material": MATERIALS[rng.randrange(len(MATERIALS))],
        "type": event_type,
        "qty": qty,
        "unit": "lb" if rng.random() < 0.2 else "kg",
        "occurred_at": iso_z(at),
        "batch": f"SB-{n // 10 + 1}",
    }
    return SimEvent(at=at, seq=n, item=item, description=f"Clean {event_type}")


def _apply_fault(event: SimEvent, kind: str, count: int, original: SimEvent | None) -> None:
    item = event.item
    if kind == "missing_qty":
        del item["qty"]
    elif kind == "unknown_unit":
        item["unit"] = "tonnes"
    elif kind == "bad_timestamp":
        item["occurred_at"] = BAD_TIMESTAMPS[count % len(BAD_TIMESTAMPS)]
    elif kind == "unknown_type":
        item["type"] = "TRANSFER"
    elif kind == "negative_shipment":
        item["type"] = "SHIPMENT"
        item["qty"] = "-" + item["qty"].lstrip("-")
    elif kind == "conflicting_qty":
        # A resend of an earlier clean event with a different qty: same id, same time.
        assert original is not None
        event.item = {**original.item, "qty": f"{original.item['qty'].lstrip('-')}5"}
        event.at = original.at
    status, codes, description = FAULTS[kind]
    event.expected_status, event.expected_rule_codes, event.description = status, codes, description


def generate_events(seed: int = SEED, count: int = EVENT_COUNT) -> list[SimEvent]:
    """The full data set, sorted by time then id (generation order breaks ties)."""
    rng = random.Random(seed)
    events = [_clean_event(rng, n) for n in range(count)]

    faulty = sorted(rng.sample(range(1, count), round(count * FAULT_RATE)))
    kinds = list(FAULTS)
    clean_before = [n for n in range(count) if n not in faulty]
    for i, n in enumerate(faulty):
        kind = kinds[i % len(kinds)]
        original = None
        if kind == "conflicting_qty":
            original = events[rng.choice([c for c in clean_before if c < n])]
        _apply_fault(events[n], kind, i // len(kinds), original)

    return sorted(events, key=lambda e: (e.at, e.item["id"], e.seq))


def write_expected_outcomes(path: str) -> None:
    """Write the labeled outcomes, one row per item in response order (row_number is 1-based)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            ["fixture", "row_number", "source_record_id", "expected_status", "expected_rule_codes", "description"]
        )
        for row_number, event in enumerate(generate_events(), start=1):
            writer.writerow(
                [
                    "simulated_api",
                    row_number,
                    event.item["id"],
                    event.expected_status,
                    event.expected_rule_codes,
                    event.description,
                ]
            )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    write_expected_outcomes(sys.argv[1])
