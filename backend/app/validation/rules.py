"""Record-level validation rules (SRS §6, VAL-001..VAL-006, VAL-008).

Each rule takes the raw record and its normalized event and returns a list of
issues. Duplicate and conflict checks (VAL-007, VAL-009) need stored state and
live in app.pipeline.
"""
from __future__ import annotations

from typing import Callable

from app.config import EVENT_TYPES, REQUIRED_FIELDS, SIGNED_EVENT_TYPES
from app.models import (
    NormalizedEvent,
    RawRecord,
    Severity,
    ValidationIssue,
    ValidationStatus,
)
from app.normalization.normalize import clean_text

Rule = Callable[[RawRecord, NormalizedEvent], list[ValidationIssue]]


def _raw(raw: RawRecord, field: str) -> str | None:
    return raw.payload.get(field)


def _present(raw: RawRecord, field: str) -> bool:
    return clean_text(_raw(raw, field)) is not None


def check_required_fields(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """VAL-001: one issue per missing required field."""
    return [
        ValidationIssue("VAL-001", f, f"Required field '{f}' is missing or blank.", Severity.ERROR, _raw(raw, f))
        for f in REQUIRED_FIELDS
        if not _present(raw, f)
    ]


def check_quantity_numeric(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """VAL-002: a present quantity must parse as a decimal."""
    if _present(raw, "quantity") and event.quantity is None:
        value = _raw(raw, "quantity")
        return [ValidationIssue("VAL-002", "quantity", f"Quantity '{value}' is not a valid decimal number.", Severity.ERROR, value)]
    return []


def check_quantity_sign(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """VAL-003: negative quantities are flagged unless the event type is signed."""
    if event.quantity is not None and event.quantity < 0 and event.event_type not in SIGNED_EVENT_TYPES:
        value = _raw(raw, "quantity")
        return [
            ValidationIssue(
                "VAL-003",
                "quantity",
                f"Negative quantity {value} is not allowed for event type {event.event_type}; "
                "only " + ", ".join(sorted(SIGNED_EVENT_TYPES)) + " may be negative.",
                Severity.WARNING,
                value,
            )
        ]
    return []


def check_unit(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """VAL-004: only supported units are converted."""
    if _present(raw, "unit") and event.unit is None:
        value = _raw(raw, "unit")
        return [ValidationIssue("VAL-004", "unit", f"Unit '{value}' is not supported. Use kg or lb.", Severity.ERROR, value)]
    return []


def check_timestamp(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """VAL-005: timestamps must be ISO 8601 with an explicit timezone."""
    if _present(raw, "event_timestamp") and event.event_timestamp is None:
        value = _raw(raw, "event_timestamp")
        return [
            ValidationIssue(
                "VAL-005",
                "event_timestamp",
                f"Timestamp '{value}' is not ISO 8601 with a timezone (e.g. 2026-10-01T09:00:00Z).",
                Severity.ERROR,
                value,
            )
        ]
    return []


def check_event_type(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """VAL-006: event type must be in the configured list."""
    if _present(raw, "event_type") and event.event_type not in EVENT_TYPES:
        value = _raw(raw, "event_type")
        return [
            ValidationIssue(
                "VAL-006",
                "event_type",
                f"Event type '{value}' is not allowed. Allowed: " + ", ".join(sorted(EVENT_TYPES)) + ".",
                Severity.ERROR,
                value,
            )
        ]
    return []


def check_material_alias(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """VAL-008: unknown material names are flagged for review, not rejected."""
    if _present(raw, "material_name") and event.material_code is None:
        value = _raw(raw, "material_name")
        return [ValidationIssue("VAL-008", "material_name", f"Material '{value}' has no known alias; review and map it.", Severity.WARNING, value)]
    return []


def check_row_shape(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    """Rows with extra or missing cells are structurally suspect (part of VAL-001)."""
    issues = []
    if "_extra_cells" in raw.payload:
        issues.append(ValidationIssue("VAL-001", None, "Row has more cells than the header.", Severity.ERROR, raw.payload["_extra_cells"]))
    if "_short_row" in raw.payload:
        issues.append(ValidationIssue("VAL-001", None, "Row has fewer cells than the header.", Severity.ERROR, raw.payload["_short_row"]))
    return issues


RECORD_RULES: tuple[Rule, ...] = (
    check_row_shape,
    check_required_fields,
    check_quantity_numeric,
    check_quantity_sign,
    check_unit,
    check_timestamp,
    check_event_type,
    check_material_alias,
)


def validate_record(raw: RawRecord, event: NormalizedEvent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for rule in RECORD_RULES:
        issues.extend(rule(raw, event))
    return issues


def status_for(issues: list[ValidationIssue]) -> ValidationStatus:
    if any(i.severity is Severity.ERROR for i in issues):
        return ValidationStatus.QUARANTINED
    if issues:
        return ValidationStatus.FLAGGED
    return ValidationStatus.ACCEPTED
