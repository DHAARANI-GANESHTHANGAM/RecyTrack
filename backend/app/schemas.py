"""Request and response models for the REST API (SRS §8).

Decimal quantities are serialized as strings so no precision is lost in JSON.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import MATERIAL_ALIASES

T = TypeVar("T")


class ReviewStatus(str, Enum):
    OPEN = "OPEN"  # not reviewed yet
    APPROVED = "APPROVED"  # reviewer confirms the data is usable despite the issue
    REJECTED = "REJECTED"  # reviewer confirms the record is wrong; keep it out of totals
    NEEDS_INFO = "NEEDS_INFO"  # reviewer is waiting on the source for more information


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    source_name: str
    file_name: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    received_count: int
    accepted_count: int
    quarantined_count: int
    flagged_count: int
    duplicate_count: int
    error_summary: str | None


class IssueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issue_id: int
    rule_code: str
    field_name: str | None
    message: str
    severity: str
    raw_value: str | None
    review_status: str
    created_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    run_id: str
    raw_id: str
    source_name: str
    source_record_id: str | None
    facility_id: str | None
    material_name_raw: str | None
    material_code: str | None
    event_type: str | None
    quantity: Decimal | None
    unit_raw: str | None
    unit: str | None
    quantity_kg: Decimal | None
    event_timestamp_raw: str | None
    event_timestamp: datetime | None
    batch_id: str | None
    validation_status: str
    created_at: datetime


class ExceptionSummary(EventOut):
    issues: list[IssueOut]


class RawRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    raw_id: str
    row_number: int
    raw_payload: dict
    payload_hash: str
    received_at: datetime


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: int
    action: str
    actor_label: str
    details: dict
    created_at: datetime


class ExceptionDetail(BaseModel):
    """Everything needed to investigate one exception (UC-03)."""

    event: EventOut
    raw: RawRecordOut
    run: RunOut
    issues: list[IssueOut]
    review_history: list[AuditOut]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    filters: dict


class ReviewIn(BaseModel):
    review_status: ReviewStatus
    actor_label: str = Field(min_length=1, max_length=100, description="Who made the decision, e.g. 'analyst-1'.")
    note: str | None = Field(default=None, max_length=2000)


class ReviewOut(BaseModel):
    event_id: str
    review_status: ReviewStatus
    audit: AuditOut


class QualityMetrics(BaseModel):
    run_id: str | None
    runs: int
    failed_runs: int
    received: int
    accepted: int
    quarantined: int
    flagged: int
    duplicates: int
    acceptance_rate: float | None
    quarantine_rate: float | None
    flag_rate: float | None
    duplicate_rate: float | None
    open_exceptions: int
    issues_by_rule: dict[str, int]

# ---------------------------------------------------------------- reconciliation (M5)

MATERIAL_CODES = frozenset(MATERIAL_ALIASES.values())


class ReconciliationIn(BaseModel):
    facility_id: str = Field(min_length=1, max_length=50, examples=["FAC-10"])
    material_code: str = Field(examples=["PLASTIC_FILM"])
    period_start: AwareDatetime = Field(description="ISO 8601 with a timezone offset, e.g. 2026-10-01T00:00:00Z.")
    period_end: AwareDatetime = Field(description="ISO 8601 with a timezone offset. Must be after period_start.")
    absolute_tolerance_kg: Decimal | None = Field(default=None, ge=0, description="Defaults to the configured value.")
    percent_tolerance: Decimal | None = Field(
        default=None, ge=0, description="Percent of throughput. Defaults to the configured value."
    )
    actor_label: str = Field(default="system", min_length=1, max_length=100)

    @field_validator("facility_id", "material_code")
    @classmethod
    def _upper(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("material_code")
    @classmethod
    def _known_material(cls, value: str) -> str:
        if value not in MATERIAL_CODES:
            raise ValueError("unknown material_code; use one of " + ", ".join(sorted(MATERIAL_CODES)))
        return value

    @model_validator(mode="after")
    def _period_order(self) -> "ReconciliationIn":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


class ReconciliationOut(BaseModel):
    """One reconciliation snapshot. Kg values are null when they could not be calculated."""

    model_config = ConfigDict(from_attributes=True)

    reconciliation_id: str
    facility_id: str
    material_code: str
    period_start: datetime
    period_end: datetime
    opening_stock_kg: Decimal | None
    receipts_kg: Decimal | None
    production_kg: Decimal | None
    adjustments_kg: Decimal | None
    shipments_kg: Decimal | None
    losses_kg: Decimal | None
    consumption_kg: Decimal | None
    closing_stock_kg: Decimal | None
    expected_closing_kg: Decimal | None
    variance_kg: Decimal | None
    throughput_kg: Decimal | None
    tolerance_kg: Decimal | None
    tolerance_absolute_kg: Decimal
    tolerance_percent: Decimal
    status: str = Field(description="WITHIN_TOLERANCE, NEEDS_REVIEW (a review flag, not proof of an error) or NEEDS_DATA")
    reasons: list[str]
    created_at: datetime


class LinkedEventOut(BaseModel):
    event_id: str
    source_record_id: str | None
    event_type: str | None
    quantity_kg: Decimal | None
    event_timestamp: datetime | None
    validation_status: str
    excluded_reason: str | None


class ReconciliationDetail(ReconciliationOut):
    """A snapshot with the formula, the tolerance and every event it used or left out (FR-15)."""

    formula: str
    tolerance_explanation: str
    events: dict[str, list[LinkedEventOut]]

# ---------------------------------------------------------------- dashboard (M6)


class ToleranceOut(BaseModel):
    absolute_kg: Decimal
    percent_of_throughput: Decimal


class MetaOut(BaseModel):
    """Valid values for the dashboard's dropdowns."""

    event_types: list[str]
    material_codes: list[str]
    facilities: list[str]
    validation_statuses: list[str]
    review_statuses: list[str]
    reconciliation_statuses: list[str]
    default_tolerance: ToleranceOut
