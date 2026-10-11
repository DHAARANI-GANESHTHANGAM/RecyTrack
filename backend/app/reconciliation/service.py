"""Load events from the database, reconcile them and save the snapshot (FR-10, FR-11, FR-15)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import RECONCILIATION_TOLERANCE
from app.database.tables import (
    AuditEventRow,
    MaterialEventRow,
    ReconciliationEventRow,
    ReconciliationRow,
)
from app.models import utc_now
from app.reconciliation.engine import ReconEvent, exclusion_reason, reconcile


def _to_recon_event(row: MaterialEventRow) -> ReconEvent:
    return ReconEvent(
        event_id=row.event_id,
        facility_id=row.facility_id,
        material_code=row.material_code,
        event_type=row.event_type,
        quantity_kg=row.quantity_kg,
        event_timestamp=row.event_timestamp,
        validation_status=row.validation_status,
        review_statuses=tuple(i.review_status for i in row.issues),
        source_record_id=row.source_record_id,
    )


def load_candidate_events(
    session: Session, facility_id: str, material_code: str, period_start: datetime, period_end: datetime
) -> list[ReconEvent]:
    """Every event the balance could use: earlier counts, then everything from the opening count to period_end."""
    e = MaterialEventRow
    base = (
        select(e)
        .where(e.facility_id == facility_id, e.material_code == material_code, e.event_timestamp.is_not(None))
        .options(selectinload(e.issues))
    )
    earlier_counts = [
        _to_recon_event(r)
        for r in session.scalars(base.where(e.event_type == "INVENTORY_COUNT", e.event_timestamp <= period_start))
    ]
    # Flows count from the opening count onward, which may be before period_start.
    lower = max((c.event_timestamp for c in earlier_counts if exclusion_reason(c) is None), default=period_start)
    events = {c.event_id: c for c in earlier_counts}
    for r in session.scalars(base.where(e.event_timestamp >= lower, e.event_timestamp <= period_end)):
        events.setdefault(r.event_id, _to_recon_event(r))
    return list(events.values())


def run_reconciliation(
    session: Session,
    facility_id: str,
    material_code: str,
    period_start: datetime,
    period_end: datetime,
    tolerance: Mapping[str, Decimal] = RECONCILIATION_TOLERANCE,
    actor_label: str = "system",
) -> ReconciliationRow:
    """Reconcile and save a new snapshot with its linked events and an audit row.

    Writes go into the caller's session; the caller commits or rolls back.
    """
    events = load_candidate_events(session, facility_id, material_code, period_start, period_end)
    result = reconcile(events, facility_id, material_code, period_start, period_end, tolerance)

    row = ReconciliationRow(
        reconciliation_id=str(uuid.uuid4()),
        facility_id=result.facility_id,
        material_code=result.material_code,
        period_start=result.period_start,
        period_end=result.period_end,
        opening_stock_kg=result.opening_stock_kg,
        receipts_kg=result.receipts_kg,
        production_kg=result.production_kg,
        adjustments_kg=result.adjustments_kg,
        shipments_kg=result.shipments_kg,
        losses_kg=result.losses_kg,
        consumption_kg=result.consumption_kg,
        closing_stock_kg=result.closing_stock_kg,
        expected_closing_kg=result.expected_closing_kg,
        variance_kg=result.variance_kg,
        throughput_kg=result.throughput_kg,
        tolerance_kg=result.tolerance_kg,
        tolerance_absolute_kg=result.tolerance_absolute_kg,
        tolerance_percent=result.tolerance_percent,
        status=result.status.value,
        reasons=list(result.reasons),
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()  # parent row first, so the links' foreign keys resolve on every database
    for link in result.links:
        session.add(
            ReconciliationEventRow(
                reconciliation_id=row.reconciliation_id,
                event_id=link.event_id,
                role=link.role,
                excluded_reason=link.excluded_reason,
            )
        )
    session.add(
        AuditEventRow(
            entity_type="reconciliation",
            entity_id=row.reconciliation_id,
            action="reconciliation_run",
            actor_label=actor_label,
            details={
                "facility_id": row.facility_id,
                "material_code": row.material_code,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
                "status": row.status,
                "variance_kg": None if row.variance_kg is None else str(row.variance_kg),
                "tolerance_kg": None if row.tolerance_kg is None else str(row.tolerance_kg),
                "event_count": len(result.links),
            },
            created_at=utc_now(),
        )
    )
    session.flush()
    return row
