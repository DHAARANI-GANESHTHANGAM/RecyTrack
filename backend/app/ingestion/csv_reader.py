"""Read a CSV file into immutable RawRecord objects (FR-01, FR-02, FR-03)."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from pathlib import Path

from app.config import CSV_COLUMNS, MAX_UPLOAD_BYTES, REQUIRED_FIELDS
from app.models import RawRecord, utc_now


class CsvFormatError(ValueError):
    """The file as a whole cannot be imported. The message tells the user what to fix."""


def payload_hash(payload: dict[str, str]) -> str:
    """Stable SHA-256 of a row, independent of column order."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decode(data: bytes) -> str:
    if len(data) > MAX_UPLOAD_BYTES:
        raise CsvFormatError(
            f"File is {len(data)} bytes; the limit is {MAX_UPLOAD_BYTES} bytes. "
            "Split the file and import the parts separately."
        )
    if not data.strip():
        raise CsvFormatError("File is empty. Provide a CSV with a header row and data rows.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvFormatError(
            f"File is not valid UTF-8 (byte offset {exc.start}). Re-save the file as UTF-8 CSV."
        ) from exc


def _check_header(header: list[str] | None) -> list[str]:
    if not header:
        raise CsvFormatError("CSV has no header row. Expected columns: " + ",".join(CSV_COLUMNS))
    cleaned = [h.strip() for h in header]
    missing = [c for c in REQUIRED_FIELDS if c not in cleaned]
    unknown = [c for c in cleaned if c not in CSV_COLUMNS]
    dupes = sorted({c for c in cleaned if cleaned.count(c) > 1})
    problems = []
    if missing:
        problems.append("missing columns: " + ", ".join(missing))
    if unknown:
        problems.append("unknown columns: " + ", ".join(unknown))
    if dupes:
        problems.append("repeated columns: " + ", ".join(dupes))
    if problems:
        raise CsvFormatError(
            "CSV header does not match the contract ("
            + "; ".join(problems)
            + "). Expected columns: "
            + ",".join(CSV_COLUMNS)
        )
    return cleaned


def read_csv_bytes(data: bytes, run_id: str, source_name: str = "csv") -> list[RawRecord]:
    text = _decode(data)
    reader = csv.reader(io.StringIO(text, newline=""))
    header = _check_header(next(reader, None))

    records: list[RawRecord] = []
    received_at = utc_now()
    for row_number, row in enumerate(reader, start=2):  # row 1 is the header
        if not any(cell.strip() for cell in row):
            continue  # skip blank lines
        # Keep every value exactly as received. Pad short rows; keep extra cells.
        payload = {col: (row[i] if i < len(row) else "") for i, col in enumerate(header)}
        if len(row) > len(header):
            payload["_extra_cells"] = json.dumps(row[len(header):])
        if len(row) < len(header):
            payload["_short_row"] = str(len(row))
        records.append(
            RawRecord(
                raw_id=str(uuid.uuid4()),
                run_id=run_id,
                source_name=source_name,
                row_number=row_number,
                payload=payload,
                payload_hash=payload_hash(payload),
                received_at=received_at,
            )
        )
    return records


def read_csv_file(path: str | Path, run_id: str, source_name: str = "csv") -> list[RawRecord]:
    path = Path(path)
    if path.suffix.lower() != ".csv":
        raise CsvFormatError(f"{path.name} is not a .csv file.")
    return read_csv_bytes(path.read_bytes(), run_id, source_name)
