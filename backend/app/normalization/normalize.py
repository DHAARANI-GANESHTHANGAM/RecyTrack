"""Normalization helpers (FR-04).

Each function returns either a normalized value or None. Functions never raise on
bad input and never modify the raw record; validation decides what a None means.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.config import KG_PER_UNIT, MATERIAL_ALIASES, UNIT_ALIASES
from app.models import NormalizedEvent, RawRecord

_WS = re.compile(r"\s+")


def clean_text(value: str | None) -> str | None:
    """Trim and collapse internal whitespace; empty -> None."""
    if value is None:
        return None
    cleaned = _WS.sub(" ", value).strip()
    return cleaned or None


def parse_quantity(value: str | None) -> Decimal | None:
    """Parse a decimal quantity. Accepts thousands separators like '1,000.5'."""
    text = clean_text(value)
    if text is None:
        return None
    text = text.replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return number


def normalize_unit(value: str | None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return UNIT_ALIASES.get(text.lower().rstrip("."))


def to_kg(quantity: Decimal | None, unit: str | None) -> Decimal | None:
    if quantity is None or unit is None:
        return None
    return quantity * KG_PER_UNIT[unit]


def normalize_material(value: str | None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return MATERIAL_ALIASES.get(text.lower())


def normalize_event_type(value: str | None) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    return text.upper().replace(" ", "_").replace("-", "_")


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse ISO 8601 with an explicit offset and convert to UTC.

    Timestamps without a timezone return None: guessing the zone would be a
    silent correction (SRS REC-004 spirit, §16 timezone policy).
    """
    text = clean_text(value)
    if text is None:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def normalize_record(raw: RawRecord) -> NormalizedEvent:
    p = raw.payload
    quantity = parse_quantity(p.get("quantity"))
    unit = normalize_unit(p.get("unit"))
    return NormalizedEvent(
        event_id=str(uuid.uuid4()),
        raw_id=raw.raw_id,
        run_id=raw.run_id,
        source_name=raw.source_name,
        source_record_id=clean_text(p.get("source_record_id")),
        facility_id=(clean_text(p.get("facility_id")) or "").upper() or None,
        material_name_raw=p.get("material_name"),
        material_code=normalize_material(p.get("material_name")),
        event_type=normalize_event_type(p.get("event_type")),
        quantity=quantity,
        unit_raw=p.get("unit"),
        unit=unit,
        quantity_kg=to_kg(quantity, unit),
        event_timestamp_raw=p.get("event_timestamp"),
        event_timestamp=parse_timestamp(p.get("event_timestamp")),
        batch_id=clean_text(p.get("batch_id")),
    )
