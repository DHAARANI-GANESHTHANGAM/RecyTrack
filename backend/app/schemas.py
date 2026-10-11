"""Request and response models for the REST API (SRS §8).

Decimal quantities are serialized as strings so no precision is lost in JSON.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

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
