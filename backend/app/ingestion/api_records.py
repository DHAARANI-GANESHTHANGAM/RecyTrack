"""Map API items into immutable RawRecord objects (FR-01, FR-03).

The simulated source uses its own field names. They are mapped to the CSV contract's
names so the same normalization and validation apply. Values are kept as text exactly
as received (no cleanup), and the whole original item is kept in `_source_json`.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

from app.ingestion.csv_reader import payload_hash
from app.models import RawRecord, utc_now

SIMULATED_SOURCE = "simulated_api"

# API field -> CSV contract field (docs/data_dictionary.md).
API_FIELD_MAP = {
    "id": "source_record_id",
    "facility": "facility_id",
    "material": "material_name",
    "type": "event_type",
    "qty": "quantity",
    "unit": "unit",
    "occurred_at": "event_timestamp",
    "batch": "batch_id",
}


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _compact_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)


def _as_text(value) -> str:
    """The value as text without cleanup. Missing or null -> ""."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal)):
        return str(value)
    return _compact_json(value)  # objects, lists and anything else


def records_from_api_items(items: list[dict], run_id: str, source_name: str = SIMULATED_SOURCE) -> list[RawRecord]:
    received_at = utc_now()
    records: list[RawRecord] = []
    for row_number, item in enumerate(items, start=1):
        payload = {target: _as_text(item.get(source)) for source, target in API_FIELD_MAP.items()}
        extra = sorted(k for k in item if k not in API_FIELD_MAP)
        if extra:
            payload["_extra_fields"] = _compact_json(extra)  # structurally suspect: VAL-001
        payload["_source_json"] = _compact_json(item)
        records.append(
            RawRecord(
                raw_id=str(uuid.uuid4()),
                run_id=run_id,
                source_name=source_name,
                row_number=row_number,
                payload=payload,
                payload_hash=payload_hash(payload),
                received_at=received_at,
            )
        )
    return records
