"""Core data objects shared by ingestion, normalization, validation and storage."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Severity(str, Enum):
    ERROR = "ERROR"  # record cannot be trusted -> QUARANTINED
    WARNING = "WARNING"  # record is usable but suspicious -> FLAGGED


class ValidationStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    FLAGGED = "FLAGGED"
    DUPLICATE = "DUPLICATE"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RawRecord:
    """An input row exactly as received. Never modified after creation (FR-03)."""

    raw_id: str
    run_id: str
    source_name: str
    row_number: int
    payload: Mapping[str, str]
    payload_hash: str
    received_at: datetime

    def __post_init__(self) -> None:
        # Freeze the payload so no later stage can rewrite the original values.
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @property
    def source_record_id(self) -> str | None:
        value = (self.payload.get("source_record_id") or "").strip()
        return value or None


@dataclass(frozen=True)
class ValidationIssue:
    rule_code: str
    field_name: str | None
    message: str
    severity: Severity
    raw_value: str | None = None


@dataclass
class NormalizedEvent:
    """Normalized view of a raw record. Fields are None when they could not be normalized."""

    event_id: str
    raw_id: str
    run_id: str
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
    validation_status: ValidationStatus = ValidationStatus.ACCEPTED
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass
class IngestionRun:
    source_name: str
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.RUNNING
    received_count: int = 0
    accepted_count: int = 0
    quarantined_count: int = 0
    flagged_count: int = 0
    duplicate_count: int = 0
    error_summary: str | None = None

    def summary(self) -> dict:
        received = self.received_count or 0

        def rate(n: int) -> float | None:
            return round(n / received, 4) if received else None

        return {
            "run_id": self.run_id,
            "source_name": self.source_name,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "received": self.received_count,
            "accepted": self.accepted_count,
            "quarantined": self.quarantined_count,
            "flagged": self.flagged_count,
            "duplicates": self.duplicate_count,
            "acceptance_rate": rate(self.accepted_count),
            "quarantine_rate": rate(self.quarantined_count),
            "error_summary": self.error_summary,
        }
