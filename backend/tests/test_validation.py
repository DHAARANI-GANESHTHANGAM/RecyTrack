import pytest

from app.models import Severity, ValidationStatus
from app.normalization.normalize import normalize_record
from app.validation.rules import status_for, validate_record
from tests.conftest import make_raw


def codes_for(**overrides):
    raw = make_raw(**overrides)
    issues = validate_record(raw, normalize_record(raw))
    return issues, status_for(issues)


def test_clean_row_is_accepted():
    issues, status = codes_for()
    assert issues == []
    assert status is ValidationStatus.ACCEPTED


def test_batch_id_is_optional():
    issues, status = codes_for(batch_id="")
    assert status is ValidationStatus.ACCEPTED


@pytest.mark.parametrize(
    "field", ["source_record_id", "facility_id", "material_name", "event_type", "quantity", "unit", "event_timestamp"]
)
def test_val001_each_missing_required_field_is_named(field):
    issues, status = codes_for(**{field: "   "})
    assert status is ValidationStatus.QUARANTINED
    assert [(i.rule_code, i.field_name) for i in issues] == [("VAL-001", field)]


def test_val001_reports_every_missing_field():
    issues, _ = codes_for(quantity="", unit="", facility_id="")
    assert sorted(i.field_name for i in issues if i.rule_code == "VAL-001") == ["facility_id", "quantity", "unit"]


def test_val002_unparseable_quantity():
    issues, status = codes_for(quantity="12kg")
    assert status is ValidationStatus.QUARANTINED
    assert issues[0].rule_code == "VAL-002"
    assert issues[0].raw_value == "12kg"


def test_val003_negative_quantity_is_flagged_not_quarantined():
    issues, status = codes_for(event_type="SHIPMENT", quantity="-5")
    assert status is ValidationStatus.FLAGGED
    assert [i.rule_code for i in issues] == ["VAL-003"]
    assert issues[0].severity is Severity.WARNING


def test_val003_signed_adjustment_is_allowed():
    issues, status = codes_for(event_type="INVENTORY_ADJUSTMENT", quantity="-5")
    assert status is ValidationStatus.ACCEPTED


def test_val003_zero_is_not_negative():
    _, status = codes_for(quantity="0")
    assert status is ValidationStatus.ACCEPTED


def test_val004_unsupported_unit():
    issues, status = codes_for(unit="tonnes")
    assert status is ValidationStatus.QUARANTINED
    assert [i.rule_code for i in issues] == ["VAL-004"]


@pytest.mark.parametrize("ts", ["2026-10-01T09:00:00", "not a date", "2026-02-30T00:00:00Z"])
def test_val005_invalid_or_naive_timestamp(ts):
    issues, status = codes_for(event_timestamp=ts)
    assert status is ValidationStatus.QUARANTINED
    assert [i.rule_code for i in issues] == ["VAL-005"]


def test_val006_unknown_event_type():
    issues, status = codes_for(event_type="TRANSFER")
    assert status is ValidationStatus.QUARANTINED
    assert [i.rule_code for i in issues] == ["VAL-006"]


def test_val008_unknown_material_is_flagged():
    issues, status = codes_for(material_name="Mystery polymer")
    assert status is ValidationStatus.FLAGGED
    assert [i.rule_code for i in issues] == ["VAL-008"]


def test_error_outranks_warning():
    issues, status = codes_for(material_name="Mystery polymer", unit="tons")
    assert {i.rule_code for i in issues} == {"VAL-004", "VAL-008"}
    assert status is ValidationStatus.QUARANTINED


def test_every_issue_has_a_message():
    issues, _ = codes_for(quantity="x", unit="y", event_type="z", event_timestamp="w", material_name="v")
    assert len(issues) == 5
    assert all(i.message and i.rule_code.startswith("VAL-") for i in issues)
