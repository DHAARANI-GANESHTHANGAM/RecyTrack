"""Storage interface. InMemoryRepository is used until the PostgreSQL store (M4)."""
from __future__ import annotations

from typing import Protocol

from app.models import IngestionRun, NormalizedEvent, RawRecord

StableKey = tuple[str, str]  # (source_name, source_record_id)


class Repository(Protocol):
    def save_run(self, run: IngestionRun) -> None: ...
    def save_raw(self, raw: RawRecord) -> None: ...
    def save_event(self, event: NormalizedEvent, payload_hash: str) -> None: ...
    def find_hashes_for_key(self, key: StableKey) -> set[str]: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.runs: dict[str, IngestionRun] = {}
        self.raw_records: list[RawRecord] = []
        self.events: list[NormalizedEvent] = []
        self._hashes_by_key: dict[StableKey, set[str]] = {}

    def save_run(self, run: IngestionRun) -> None:
        self.runs[run.run_id] = run

    def save_raw(self, raw: RawRecord) -> None:
        self.raw_records.append(raw)

    def save_event(self, event: NormalizedEvent, payload_hash: str) -> None:
        self.events.append(event)
        if event.source_record_id:
            key = (event.source_name, event.source_record_id)
            self._hashes_by_key.setdefault(key, set()).add(payload_hash)

    def find_hashes_for_key(self, key: StableKey) -> set[str]:
        return set(self._hashes_by_key.get(key, set()))
