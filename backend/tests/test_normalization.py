from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.normalization.normalize import (
    clean_text,
    normalize_event_type,
    normalize_material,
    normalize_record,
    normalize_unit,
    parse_quantity,
    parse_timestamp,
    to_kg,
)
from tests.conftest import make_raw


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1000", Decimal("1000")),
        ("  12.50 ", Decimal("12.50")),
        ("1,500", Decimal("1500")),
        ("-3", Decimal("-3")),
        ("0", Decimal("0")),
        ("abc", None),
        ("", None),
        (None, None),
        ("NaN", None),
        ("Infinity", None),
        ("1.2.3", None),
    ],
)
def test_parse_quantity(raw, expected):
    assert parse_quantity(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("kg", "kg"), ("KG", "kg"), ("kgs", "kg"), ("Kilograms", "kg"), ("lb", "lb"),
     ("lbs.", "lb"), ("Pound", "lb"), ("tons", None), ("", None), (None, None)],
)
def test_normalize_unit(raw, expected):
    assert normalize_unit(raw) == expected


def test_pound_conversion_uses_exact_constant():
    assert to_kg(Decimal("1"), "lb") == Decimal("0.45359237")
    assert to_kg(Decimal("1000"), "lb") == Decimal("453.59237000")
    assert to_kg(Decimal("2.5"), "kg") == Decimal("2.5")
    assert to_kg(None, "kg") is None
    assert to_kg(Decimal("1"), None) is None


@pytest.mark.parametrize(
    "raw, expected",
    [("Plastic film", "PLASTIC_FILM"), ("  plastic   FILM - mixed ", "PLASTIC_FILM"),
     ("PCR resin", "RECYCLED_RESIN"), ("Mystery polymer", None), ("", None)],
)
def test_normalize_material(raw, expected):
    assert normalize_material(raw) == expected


def test_normalize_event_type():
    assert normalize_event_type(" shipment ") == "SHIPMENT"
    assert normalize_event_type("inventory adjustment") == "INVENTORY_ADJUSTMENT"
    assert normalize_event_type("Inventory-Adjustment") == "INVENTORY_ADJUSTMENT"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-10-01T09:00:00Z", datetime(2026, 10, 1, 9, tzinfo=timezone.utc)),
        ("2026-10-02T08:15:00+02:00", datetime(2026, 10, 2, 6, 15, tzinfo=timezone.utc)),
        ("2026-10-04T23:30:00-05:00", datetime(2026, 10, 5, 4, 30, tzinfo=timezone.utc)),
        ("2026-10-01T09:00:00", None),  # no timezone -> not guessed
        ("2026-13-45T25:00:00Z", None),
        ("01/10/2026", None),
        ("", None),
    ],
)
def test_parse_timestamp(raw, expected):
    assert parse_timestamp(raw) == expected


def test_clean_text_collapses_whitespace():
    assert clean_text("  a   b \t c ") == "a b c"
    assert clean_text("   ") is None


def test_normalize_record_keeps_raw_values_untouched():
    raw = make_raw(material_name="  Plastic film - mixed ", unit="LBS", quantity="10", facility_id="fac-01")
    original = dict(raw.payload)
    event = normalize_record(raw)

    assert dict(raw.payload) == original
    assert event.material_name_raw == "  Plastic film - mixed "
    assert event.material_code == "PLASTIC_FILM"
    assert event.unit_raw == "LBS"
    assert event.unit == "lb"
    assert event.quantity_kg == Decimal("4.5359237")
    assert event.facility_id == "FAC-01"
    assert event.event_timestamp_raw == "2026-10-01T09:00:00Z"


def test_raw_payload_is_read_only():
    raw = make_raw()
    with pytest.raises(TypeError):
        raw.payload["quantity"] = "5"  # type: ignore[index]
