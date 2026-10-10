"""PostgreSQL schema (SRS §5.2) as SQLAlchemy ORM tables.

The reconciliations table is added with milestone M5.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.models import utc_now


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime that always comes back in UTC, on every database."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetimes are not stored; convert to UTC first")
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite drops the offset; values were stored as UTC
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class ExactDecimal(TypeDecorator):
    """NUMERIC on PostgreSQL; text on SQLite so decimals never pass through float."""

    impl = Numeric(24, 10)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(64))
        return dialect.type_descriptor(Numeric(24, 10))

    def process_bind_param(self, value: Decimal | None, dialect):
        if value is None:
            return None
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return strip_zeros(Decimal(value))


def strip_zeros(value: Decimal) -> Decimal:
    """1000.0000000000 -> 1000 and 12.5000 -> 12.5, without switching to exponent form."""
    if value == value.to_integral_value():
        return value.quantize(Decimal(1))
    return value.normalize()


Payload = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class IngestionRunRow(Base):
    __tablename__ = "ingestion_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(50))
    file_name: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), index=True)
    received_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    quarantined_count: Mapped[int] = mapped_column(Integer, default=0)
    flagged_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)


class RawRecordRow(Base):
    """Immutable copy of every input row (FR-03). Rows are inserted, never updated."""

    __tablename__ = "raw_records"

    raw_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.run_id"), index=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str | None] = mapped_column(String(100), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    raw_payload: Mapped[dict] = mapped_column(Payload)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())


class MaterialEventRow(Base):
    __tablename__ = "material_events"
    __table_args__ = (
        # VAL-007 enforced by the database too: the same source record with the same
        # content can exist only once, even if two imports run at the same time.
        UniqueConstraint("source_name", "source_record_id", "payload_hash", name="uq_event_source_payload"),
        Index("ix_events_facility_material_time", "facility_id", "material_code", "event_timestamp"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    raw_id: Mapped[str] = mapped_column(ForeignKey("raw_records.raw_id"), unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("ingestion_runs.run_id"), index=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str | None] = mapped_column(String(100))
    payload_hash: Mapped[str] = mapped_column(String(64))
    facility_id: Mapped[str | None] = mapped_column(String(50))
    material_name_raw: Mapped[str | None] = mapped_column(String(255))
    material_code: Mapped[str | None] = mapped_column(String(50))
    event_type: Mapped[str | None] = mapped_column(String(50), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    unit_raw: Mapped[str | None] = mapped_column(String(50))
    unit: Mapped[str | None] = mapped_column(String(10))
    quantity_kg: Mapped[Decimal | None] = mapped_column(ExactDecimal())
    event_timestamp_raw: Mapped[str | None] = mapped_column(String(100))
    event_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime())
    batch_id: Mapped[str | None] = mapped_column(String(100), index=True)
    validation_status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    raw: Mapped[RawRecordRow] = relationship()
    run: Mapped[IngestionRunRow] = relationship()
    issues: Mapped[list["ValidationIssueRow"]] = relationship(
        back_populates="event", order_by="ValidationIssueRow.issue_id"
    )


class ValidationIssueRow(Base):
    __tablename__ = "validation_issues"

    issue_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("material_events.event_id"), index=True)
    raw_id: Mapped[str] = mapped_column(ForeignKey("raw_records.raw_id"))
    rule_code: Mapped[str] = mapped_column(String(20), index=True)
    field_name: Mapped[str | None] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(10))
    raw_value: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    event: Mapped[MaterialEventRow] = relationship(back_populates="issues")


class AuditEventRow(Base):
    """Append-only log of review decisions and run completions (FR-20)."""

    __tablename__ = "audit_events"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(50))
    actor_label: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(Payload)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
