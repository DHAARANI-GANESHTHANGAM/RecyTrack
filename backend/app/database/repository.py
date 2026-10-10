"""SQL implementation of the Repository interface in app.store."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.tables import (
    IngestionRunRow,
    MaterialEventRow,
    RawRecordRow,
    ValidationIssueRow,
)
from app.models import IngestionRun, NormalizedEvent, RawRecord
from app.store import StableKey


class SqlRepository:
    """Writes go into the caller's session; the caller commits or rolls back."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save_run(self, run: IngestionRun) -> None:
        self.session.merge(
            IngestionRunRow(
                run_id=run.run_id,
                source_name=run.source_name,
                file_name=run.file_name,
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status.value,
                received_count=run.received_count,
                accepted_count=run.accepted_count,
                quarantined_count=run.quarantined_count,
                flagged_count=run.flagged_count,
                duplicate_count=run.duplicate_count,
                error_summary=run.error_summary,
            )
        )
        self.session.flush()

    def save_raw(self, raw: RawRecord) -> None:
        self.session.add(
            RawRecordRow(
                raw_id=raw.raw_id,
                run_id=raw.run_id,
                source_name=raw.source_name,
                source_record_id=raw.source_record_id,
                row_number=raw.row_number,
                raw_payload=dict(raw.payload),
                payload_hash=raw.payload_hash,
                received_at=raw.received_at,
            )
        )

    def save_event(self, event: NormalizedEvent, payload_hash: str) -> None:
        self.session.add(
            MaterialEventRow(
                event_id=event.event_id,
                raw_id=event.raw_id,
                run_id=event.run_id,
                source_name=event.source_name,
                source_record_id=event.source_record_id,
                payload_hash=payload_hash,
                facility_id=event.facility_id,
                material_name_raw=event.material_name_raw,
                material_code=event.material_code,
                event_type=event.event_type,
                quantity=event.quantity,
                unit_raw=event.unit_raw,
                unit=event.unit,
                quantity_kg=event.quantity_kg,
                event_timestamp_raw=event.event_timestamp_raw,
                event_timestamp=event.event_timestamp,
                batch_id=event.batch_id,
                validation_status=event.validation_status.value,
            )
        )
        for issue in event.issues:
            self.session.add(
                ValidationIssueRow(
                    event_id=event.event_id,
                    raw_id=event.raw_id,
                    rule_code=issue.rule_code,
                    field_name=issue.field_name,
                    message=issue.message,
                    severity=issue.severity.value,
                    raw_value=issue.raw_value,
                )
            )

    def find_hashes_for_keys(self, keys: set[StableKey]) -> dict[StableKey, set[str]]:
        """Payload hashes already stored for these keys, fetched in a few batched queries."""
        found: dict[StableKey, set[str]] = {}
        by_source: dict[str, list[str]] = {}
        for source_name, record_id in keys:
            by_source.setdefault(source_name, []).append(record_id)
        for source_name, ids in by_source.items():
            for start in range(0, len(ids), 1000):
                rows = self.session.execute(
                    select(MaterialEventRow.source_record_id, MaterialEventRow.payload_hash).where(
                        MaterialEventRow.source_name == source_name,
                        MaterialEventRow.source_record_id.in_(ids[start : start + 1000]),
                    )
                )
                for record_id, payload_hash in rows:
                    found.setdefault((source_name, record_id), set()).add(payload_hash)
        return found
