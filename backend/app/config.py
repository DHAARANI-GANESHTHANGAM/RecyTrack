"""Configuration for the RecyTrack data contract and validation rules.

Values here are illustrative starting points (SRS §16). Change them in one
place so the docs in docs/validation_rules.md stay accurate.
"""
from decimal import Decimal

# CSV contract (SRS Appendix A). Header names must match exactly.
CSV_COLUMNS = (
    "source_record_id",
    "facility_id",
    "material_name",
    "event_type",
    "quantity",
    "unit",
    "event_timestamp",
    "batch_id",
)
REQUIRED_FIELDS = (
    "source_record_id",
    "facility_id",
    "material_name",
    "event_type",
    "quantity",
    "unit",
    "event_timestamp",
)
OPTIONAL_FIELDS = ("batch_id",)

EVENT_TYPES = frozenset(
    {"RECEIPT", "PRODUCTION", "SHIPMENT", "LOSS", "INVENTORY_ADJUSTMENT"}
)
# Event types whose quantity may legitimately be negative (VAL-003).
SIGNED_EVENT_TYPES = frozenset({"INVENTORY_ADJUSTMENT"})

# Exact conversion constants to kilograms (VAL-004).
# 1 lb = 0.45359237 kg by international definition.
KG_PER_UNIT = {
    "kg": Decimal("1"),
    "lb": Decimal("0.45359237"),
}
UNIT_ALIASES = {
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
}

# Material alias table (VAL-008). Keys are lower-cased, whitespace-collapsed names.
MATERIAL_ALIASES = {
    "plastic film": "PLASTIC_FILM",
    "plastic film - mixed": "PLASTIC_FILM",
    "film plastic": "PLASTIC_FILM",
    "ldpe film": "PLASTIC_FILM",
    "plastic_film": "PLASTIC_FILM",
    "recycled resin": "RECYCLED_RESIN",
    "resin - recycled": "RECYCLED_RESIN",
    "pcr resin": "RECYCLED_RESIN",
    "recycled_resin": "RECYCLED_RESIN",
}

# Upload limit for CSV files (NFR-05).
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
