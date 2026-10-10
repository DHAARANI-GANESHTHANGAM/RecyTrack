"""REST endpoints (SRS §8)."""

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Iterator

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.config import MAX_UPLOAD_BYTES
from app.database.repository import SqlRepository
from app.database.tables import (
    AuditEventRow,
    IngestionRunRow,
    MaterialEventRow,
    RawRecordRow,
    ValidationIssueRow,
)
from app.models import RunStatus, utc_now
from app.pipeline import run_csv_ingestion
from app.schemas import (
    AuditOut,
    EventOut,
    ExceptionDetail,
    ExceptionSummary,
    IssueOut,
    Page,
    QualityMetrics,
    RawRecordOut,
    ReviewIn,
    ReviewOut,
    RunOut,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")

EXCEPTION_STATUSES = ("QUARANTINED", "FLAGGED")


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


# ---------------------------------------------------------------- ingestion


@router.post("/ingestion/csv", response_model=RunOut, status_code=201)
async def import_csv(file: UploadFile = File(...), session: Session = Depends(get_session)) -> RunOut:
    """Import a CSV file (UC-01, UC-02). Returns the run with its counts."""
    name = file.filename or "upload.csv"
    if not name.lower().endswith(".csv"):
        raise HTTPException(415, f"'{name}' is not a .csv file. Upload a CSV that follows docs/data_dictionary.md.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_BYTES} bytes. Split it and import the parts.")

    try:
        result = run_csv_ingestion(data, SqlRepository(session), file_name=name)
        session.commit()
    except IntegrityError:
        # Another import of the same records committed first. Nothing from this run is kept.
        session.rollback()
        log.warning("Import of %s conflicted with a concurrent import", name)
        raise HTTPException(409, "These records were imported by another run at the same time. Re-run the import; "
                                 "already-imported rows will be counted as duplicates.")

    run = session.get(IngestionRunRow, result.run.run_id)
    if result.run.status is RunStatus.FAILED:
        raise HTTPException(422, {"message": result.run.error_summary, "run": RunOut.model_validate(run).model_dump(mode="json")})
    return RunOut.model_validate(run)


@router.get("/ingestion/runs", response_model=Page[RunOut])
def list_runs(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(IngestionRunRow)
    if status:
        stmt = stmt.where(IngestionRunRow.status == status.upper())
    stmt = stmt.order_by(IngestionRunRow.started_at.desc())
    return _paginate(session, stmt, page, page_size, {"status": status}, RunOut)


@router.get("/ingestion/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(IngestionRunRow, run_id)
    if run is None:
        raise HTTPException(404, f"No ingestion run with id {run_id}.")
    return run


# ---------------------------------------------------------------- records


def _event_filters(
    stmt: Select,
    *,
    facility_id: str | None = None,
    material_code: str | None = None,
    event_type: str | None = None,
    source_name: str | None = None,
    status: str | None = None,
    batch_id: str | None = None,
    run_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Select:
    e = MaterialEventRow
    if facility_id:
        stmt = stmt.where(e.facility_id == facility_id.upper())
    if material_code:
        stmt = stmt.where(e.material_code == material_code.upper())
    if event_type:
        stmt = stmt.where(e.event_type == event_type.upper())
    if source_name:
        stmt = stmt.where(e.source_name == source_name)
    if status:
        stmt = stmt.where(e.validation_status == status.upper())
    if batch_id:
        stmt = stmt.where(e.batch_id == batch_id)
    if run_id:
        stmt = stmt.where(e.run_id == run_id)
    if date_from:
        stmt = stmt.where(e.event_timestamp >= _as_utc(date_from))
    if date_to:
        stmt = stmt.where(e.event_timestamp < _as_utc(date_to))
    return stmt


def _as_utc(value: datetime) -> datetime:
    """Query dates without an offset are read as UTC (the storage timezone)."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class EventFilters:
    def __init__(
        self,
        facility_id: str | None = None,
        material_code: str | None = None,
        event_type: str | None = None,
        source_name: str | None = None,
        status: str | None = Query(None, description="ACCEPTED, FLAGGED or QUARANTINED"),
        batch_id: str | None = None,
        run_id: str | None = None,
        date_from: datetime | None = Query(None, description="Inclusive, ISO 8601. No offset means UTC."),
        date_to: datetime | None = Query(None, description="Exclusive, ISO 8601. No offset means UTC."),
    ):
        self.values = {
            "facility_id": facility_id,
            "material_code": material_code,
            "event_type": event_type,
            "source_name": source_name,
            "status": status,
            "batch_id": batch_id,
            "run_id": run_id,
            "date_from": date_from,
            "date_to": date_to,
        }

    def apply(self, stmt: Select) -> Select:
        return _event_filters(stmt, **self.values)

    def echo(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in self.values.items() if v is not None}


@router.get("/records", response_model=Page[EventOut])
def list_records(
    filters: EventFilters = Depends(),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """Search normalized events (UC-04)."""
    stmt = filters.apply(select(MaterialEventRow)).order_by(
        MaterialEventRow.event_timestamp.desc(), MaterialEventRow.event_id
    )
    return _paginate(session, stmt, page, page_size, filters.echo(), EventOut)


# ---------------------------------------------------------------- quarantine


def _exception_query(filters: EventFilters, rule_code: str | None, review_status: str | None) -> Select:
    stmt = filters.apply(select(MaterialEventRow)).where(MaterialEventRow.validation_status.in_(EXCEPTION_STATUSES))
    if rule_code or review_status:
        sub = select(ValidationIssueRow.event_id)
        if rule_code:
            sub = sub.where(ValidationIssueRow.rule_code == rule_code.upper())
        if review_status:
            sub = sub.where(ValidationIssueRow.review_status == review_status.upper())
        stmt = stmt.where(MaterialEventRow.event_id.in_(sub))
    return stmt


@router.get("/quarantine", response_model=Page[ExceptionSummary])
def list_exceptions(
    filters: EventFilters = Depends(),
    rule_code: str | None = None,
    review_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """Quarantined and flagged records with their rule codes and review state."""
    stmt = (
        _exception_query(filters, rule_code, review_status)
        .options(selectinload(MaterialEventRow.issues))
        .order_by(MaterialEventRow.created_at.desc(), MaterialEventRow.event_id)
    )
    echo = filters.echo() | {k: v for k, v in {"rule_code": rule_code, "review_status": review_status}.items() if v}
    return _paginate(session, stmt, page, page_size, echo, ExceptionSummary)


def _load_exception(session: Session, event_id: str) -> MaterialEventRow:
    event = session.scalar(
        select(MaterialEventRow)
        .where(MaterialEventRow.event_id == event_id)
        .options(selectinload(MaterialEventRow.issues))
    )
    if event is None:
        raise HTTPException(404, f"No record with id {event_id}.")
    if event.validation_status not in EXCEPTION_STATUSES:
        raise HTTPException(404, f"Record {event_id} is {event.validation_status}, not an exception.")
    return event


@router.get("/quarantine/{event_id}", response_model=ExceptionDetail)
def get_exception(event_id: str, session: Session = Depends(get_session)):
    """Raw values, normalized values, issues, source and run for one exception (UC-03)."""
    event = _load_exception(session, event_id)
    history = session.scalars(
        select(AuditEventRow)
        .where(AuditEventRow.entity_type == "material_event", AuditEventRow.entity_id == event_id)
        .order_by(AuditEventRow.audit_id)
    ).all()
    return ExceptionDetail(
        event=EventOut.model_validate(event),
        raw=RawRecordOut.model_validate(event.raw),
        run=RunOut.model_validate(event.run),
        issues=[IssueOut.model_validate(i) for i in event.issues],
        review_history=[AuditOut.model_validate(a) for a in history],
    )


@router.patch("/quarantine/{event_id}/review", response_model=ReviewOut)
def review_exception(event_id: str, body: ReviewIn, session: Session = Depends(get_session)):
    """Record a review decision. Source values are never changed; the decision is audited (FR-20)."""
    event = _load_exception(session, event_id)
    previous = sorted({i.review_status for i in event.issues})
    for issue in event.issues:
        issue.review_status = body.review_status.value
    audit = AuditEventRow(
        entity_type="material_event",
        entity_id=event_id,
        action="review_decision",
        actor_label=body.actor_label.strip(),
        details={
            "previous_review_status": previous,
            "review_status": body.review_status.value,
            "note": body.note,
            "rule_codes": [i.rule_code for i in event.issues],
        },
        created_at=utc_now(),
    )
    session.add(audit)
    session.commit()
    return ReviewOut(event_id=event_id, review_status=body.review_status, audit=AuditOut.model_validate(audit))


# ---------------------------------------------------------------- metrics


@router.get("/metrics/quality", response_model=QualityMetrics)
def quality_metrics(
    run_id: str | None = None,
    started_from: datetime | None = Query(None, description="Only runs started at or after this time."),
    started_to: datetime | None = Query(None, description="Only runs started before this time."),
    session: Session = Depends(get_session),
):
    """Counts and rates for one run, a time window, or all runs (FR-14)."""
    r = IngestionRunRow
    run_filter = []
    if run_id:
        if session.get(IngestionRunRow, run_id) is None:
            raise HTTPException(404, f"No ingestion run with id {run_id}.")
        run_filter.append(r.run_id == run_id)
    if started_from:
        run_filter.append(r.started_at >= _as_utc(started_from))
    if started_to:
        run_filter.append(r.started_at < _as_utc(started_to))

    totals = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(r.received_count), 0),
            func.coalesce(func.sum(r.accepted_count), 0),
            func.coalesce(func.sum(r.quarantined_count), 0),
            func.coalesce(func.sum(r.flagged_count), 0),
            func.coalesce(func.sum(r.duplicate_count), 0),
        ).where(*run_filter)
    ).one()
    failed = session.scalar(select(func.count()).where(r.status == RunStatus.FAILED.value, *run_filter))
    runs, received, accepted, quarantined, flagged, duplicates = (int(x) for x in totals)

    run_ids = select(r.run_id).where(*run_filter)
    issue_rows = session.execute(
        select(ValidationIssueRow.rule_code, func.count())
        .join(MaterialEventRow, MaterialEventRow.event_id == ValidationIssueRow.event_id)
        .where(MaterialEventRow.run_id.in_(run_ids))
        .group_by(ValidationIssueRow.rule_code)
        .order_by(ValidationIssueRow.rule_code)
    ).all()
    open_exceptions = session.scalar(
        select(func.count(func.distinct(ValidationIssueRow.event_id)))
        .join(MaterialEventRow, MaterialEventRow.event_id == ValidationIssueRow.event_id)
        .where(ValidationIssueRow.review_status == "OPEN", MaterialEventRow.run_id.in_(run_ids))
    )

    def rate(n: int) -> float | None:
        return round(n / received, 4) if received else None

    return QualityMetrics(
        run_id=run_id,
        runs=runs,
        failed_runs=failed or 0,
        received=received,
        accepted=accepted,
        quarantined=quarantined,
        flagged=flagged,
        duplicates=duplicates,
        acceptance_rate=rate(accepted),
        quarantine_rate=rate(quarantined),
        flag_rate=rate(flagged),
        duplicate_rate=rate(duplicates),
        open_exceptions=open_exceptions or 0,
        issues_by_rule={code: count for code, count in issue_rows},
    )


# ---------------------------------------------------------------- CSV export


def _csv_safe(value) -> str:
    """Stop spreadsheet apps from running exported text as a formula (CSV injection)."""
    if value is None:
        return ""
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    if text[:1] in ("=", "+", "@", "\t", "\r") or (text[:1] == "-" and not _is_number(text)):
        return "'" + text
    return text


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _csv_response(header: list[str], rows: Iterator[list], filename: str) -> StreamingResponse:
    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(header)
        yield buf.getvalue()
        for row in rows:
            buf.seek(0)
            buf.truncate()
            writer.writerow([_csv_safe(v) for v in row])
            yield buf.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


EXCEPTION_COLUMNS = [
    "event_id", "run_id", "source_name", "source_record_id", "row_number", "facility_id",
    "material_name_raw", "event_type", "event_timestamp_raw", "validation_status", "rule_code",
    "field_name", "severity", "message", "raw_value", "review_status",
]


@router.get("/reports/exceptions.csv")
def export_exceptions(
    filters: EventFilters = Depends(),
    rule_code: str | None = None,
    review_status: str | None = None,
    session: Session = Depends(get_session),
):
    """One row per validation issue, with the same filters as /quarantine (UC-07)."""
    events = session.scalars(
        _exception_query(filters, rule_code, review_status)
        .options(selectinload(MaterialEventRow.issues), selectinload(MaterialEventRow.raw))
        .order_by(MaterialEventRow.created_at, MaterialEventRow.event_id)
    ).all()

    def rows():
        for e in events:
            for i in e.issues:
                yield [
                    e.event_id, e.run_id, e.source_name, e.source_record_id, e.raw.row_number, e.facility_id,
                    e.material_name_raw, e.event_type, e.event_timestamp_raw, e.validation_status, i.rule_code,
                    i.field_name, i.severity, i.message, i.raw_value, i.review_status,
                ]

    return _csv_response(EXCEPTION_COLUMNS, rows(), "exceptions.csv")


RECORD_COLUMNS = [
    "event_id", "run_id", "source_name", "source_record_id", "facility_id", "material_code",
    "material_name_raw", "event_type", "quantity", "unit", "quantity_kg", "event_timestamp",
    "batch_id", "validation_status",
]


@router.get("/reports/records.csv")
def export_records(filters: EventFilters = Depends(), session: Session = Depends(get_session)):
    """Filtered normalized events as CSV (FR-17)."""
    events = session.scalars(
        filters.apply(select(MaterialEventRow)).order_by(MaterialEventRow.event_timestamp, MaterialEventRow.event_id)
    ).all()
    rows = ([getattr(e, c) for c in RECORD_COLUMNS] for e in events)
    return _csv_response(RECORD_COLUMNS, rows, "records.csv")


# ---------------------------------------------------------------- helpers


def _paginate(session: Session, stmt: Select, page: int, page_size: int, filters: dict, model) -> dict:
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    items = session.scalars(stmt.limit(page_size).offset((page - 1) * page_size)).all()
    return {
        "items": [model.model_validate(i) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "filters": filters,
    }
