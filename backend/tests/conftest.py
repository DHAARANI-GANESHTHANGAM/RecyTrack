import uuid
from pathlib import Path

import pytest

from app.ingestion.csv_reader import payload_hash
from app.models import RawRecord, utc_now

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"

BASE_ROW = {
    "source_record_id": "SRC-1",
    "facility_id": "FAC-01",
    "material_name": "Plastic film",
    "event_type": "RECEIPT",
    "quantity": "1000",
    "unit": "kg",
    "event_timestamp": "2026-10-01T09:00:00Z",
    "batch_id": "BATCH-1",
}


def make_raw(**overrides) -> RawRecord:
    payload = {**BASE_ROW, **overrides}
    return RawRecord(
        raw_id=str(uuid.uuid4()),
        run_id="test-run",
        source_name="csv",
        row_number=2,
        payload=payload,
        payload_hash=payload_hash(payload),
        received_at=utc_now(),
    )


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
