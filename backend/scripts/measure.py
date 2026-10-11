"""Measure what RecyTrack does on its labeled fixtures (SRS §11, §15; M8).

Run from backend/:

    python -m scripts.measure                                       # quality, idempotency, reconciliation
    python -m scripts.measure --out ../docs/results.md              # ... and write the Markdown report
    python -m scripts.measure --database-url URL --out ../docs/results.md   # ... plus the 10,000-row timing

Deterministic and offline: the labeled sets are the CSV fixtures and the simulator's generator (no HTTP), the
reconciliation check uses an in-memory SQLite database. The timing part (NFR-08) runs only with --database-url
and needs an EMPTY database (or --reset to drop and recreate RecyTrack's tables in it).

Exits with code 1 if any exact-match, idempotency or reconciliation check is below 100%, so CI can use it as a
regression guard. Detection and false-positive rates are reported, not gated: on these sets they follow from
the exact matches.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.models import ValidationStatus
from app.pipeline import run_api_ingestion, run_csv_ingestion
from app.store import InMemoryRepository
from simulator.data import generate_events

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"
CSV_SETS = ("valid_events.csv", "invalid_events.csv")
SIMULATED_SET = "simulated_api"
PERF_ROWS = 10_000
PERF_SEED = 20261010

HONESTY_NOTE = (
    "The labeled sets were written by the developer together with the rules, so 100% shows that the rules behave "
    "**as designed** on known cases. It is **not** a real-world accuracy claim: real data would contain error types "
    "that are not in the fixtures."
)


# ---------------------------------------------------------------- labeled-set quality


@dataclass
class Outcome:
    status: str
    codes: frozenset[str]


@dataclass
class SetQuality:
    name: str
    rows: int = 0
    faulty: int = 0
    detected: int = 0
    clean: int = 0
    false_positives: int = 0
    exact: int = 0
    mismatches: list[str] = field(default_factory=list)
    expected_by_rule: Counter = field(default_factory=Counter)
    found_by_rule: Counter = field(default_factory=Counter)

    @property
    def detection_rate(self) -> Decimal | None:
        return ratio(self.detected, self.faulty)

    @property
    def false_positive_rate(self) -> Decimal | None:
        return ratio(self.false_positives, self.clean)

    def add(self, other: "SetQuality") -> None:
        for name in ("rows", "faulty", "detected", "clean", "false_positives", "exact"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.mismatches += other.mismatches
        self.expected_by_rule += other.expected_by_rule
        self.found_by_rule += other.found_by_rule


def ratio(n: int, d: int) -> Decimal | None:
    return Decimal(n) / Decimal(d) if d else None


def load_labels(path: Path, fixture: str | None = None) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if fixture is None or row["fixture"] == fixture]


def label_codes(row: dict) -> frozenset[str]:
    return frozenset(filter(None, row["expected_rule_codes"].split(";")))


def csv_outcomes(fixture: str) -> dict[int, Outcome]:
    """Import one CSV fixture into a fresh in-memory repository; outcome per row number."""
    repo = InMemoryRepository()
    result = run_csv_ingestion((FIXTURES / fixture).read_bytes(), repo, file_name=fixture)
    row_of = {r.raw_id: r.row_number for r in repo.raw_records}
    return {
        row_of[e.raw_id]: Outcome(e.validation_status.value, frozenset(i.rule_code for i in e.issues))
        for e in result.events
    }


def simulated_items() -> list[dict]:
    """The simulator's items in response order, straight from its generator (no HTTP)."""
    return [event.item for event in generate_events()]


def simulated_outcomes() -> dict[int, Outcome]:
    result = run_api_ingestion(simulated_items(), InMemoryRepository())
    return {
        n: Outcome(e.validation_status.value, frozenset(i.rule_code for i in e.issues))
        for n, e in enumerate(result.events, start=1)
    }


def compare(name: str, labels: list[dict], actual: dict[int, Outcome]) -> SetQuality:
    """Match rows by row_number. Faulty = expected status is not ACCEPTED."""
    q = SetQuality(name)
    for row in labels:
        n = int(row["row_number"])
        expected = Outcome(row["expected_status"], label_codes(row))
        got = actual.get(n, Outcome("MISSING", frozenset()))
        q.rows += 1
        q.expected_by_rule.update(expected.codes)
        q.found_by_rule.update(got.codes)
        if expected.status != ValidationStatus.ACCEPTED.value:
            q.faulty += 1
            q.detected += got.status != ValidationStatus.ACCEPTED.value
        else:
            q.clean += 1
            q.false_positives += got.status != ValidationStatus.ACCEPTED.value
        if got == expected:
            q.exact += 1
        else:
            q.mismatches.append(
                f"{name} row {n}: expected {expected.status} {sorted(expected.codes)}, got {got.status} {sorted(got.codes)}"
            )
    return q


def labeled_quality() -> list[SetQuality]:
    """One entry per labeled set, then the total."""
    labels = FIXTURES / "expected_outcomes.csv"
    sets = [compare(name, load_labels(labels, name), csv_outcomes(name)) for name in CSV_SETS]
    sets.append(
        compare(SIMULATED_SET, load_labels(FIXTURES / "simulated_expected_outcomes.csv"), simulated_outcomes())
    )
    total = SetQuality("Total")
    for q in sets:
        total.add(q)
    return sets + [total]


# ---------------------------------------------------------------- idempotency


@dataclass
class Idempotency:
    name: str
    received: int
    duplicates: int
    new_events: int  # created by the second import of the same data
    rows_with_key: int
    new_events_without_key: int  # rows with no source_record_id have no stable key and are re-evaluated

    @property
    def passed(self) -> bool:
        # Every row with a stable key is recognized as a duplicate and creates no new event.
        return self.duplicates == self.rows_with_key and self.new_events == self.new_events_without_key


def _second_import(name: str, repo: InMemoryRepository, run_twice) -> Idempotency:
    run_twice()
    before = len(repo.events)
    second = run_twice()
    added = repo.events[before:]
    without_key = sum(1 for e in added if not e.source_record_id)
    second_raw = [r for r in repo.raw_records if r.run_id == second.run.run_id]
    return Idempotency(
        name=name,
        received=second.run.received_count,
        duplicates=second.run.duplicate_count,
        new_events=len(added),
        rows_with_key=sum(1 for r in second_raw if r.source_record_id),
        new_events_without_key=without_key,
    )


def idempotency() -> list[Idempotency]:
    """Import each labeled set twice into the same repository."""
    results = []
    for name in CSV_SETS:
        repo = InMemoryRepository()
        data = (FIXTURES / name).read_bytes()
        results.append(_second_import(name, repo, lambda: run_csv_ingestion(data, repo, file_name=name)))
    repo = InMemoryRepository()
    items = simulated_items()
    results.append(_second_import(SIMULATED_SET, repo, lambda: run_api_ingestion(items, repo)))
    return results


# ---------------------------------------------------------------- reconciliation


@dataclass
class ReconciliationCheck:
    scenario: str
    facility_id: str
    material_code: str
    expected_status: str
    status: str
    expected_variance_kg: Decimal | None
    variance_kg: Decimal | None
    expected_tolerance_kg: Decimal
    tolerance_kg: Decimal | None

    @property
    def matches(self) -> bool:
        return (
            self.status == self.expected_status
            and self.variance_kg == self.expected_variance_kg
            and self.tolerance_kg == self.expected_tolerance_kg
        )


def _dec(value) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def reconciliation() -> list[ReconciliationCheck]:
    """Import the scenarios through the API (TestClient, in-memory SQLite) and run every expected check."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app("sqlite://", init_attempts=1)
    checks = []
    with TestClient(app) as client:
        data = (FIXTURES / "reconciliation_scenarios.csv").read_bytes()
        r = client.post("/api/v1/ingestion/csv", files={"file": ("reconciliation_scenarios.csv", data, "text/csv")})
        r.raise_for_status()
        for row in load_labels(FIXTURES / "expected_reconciliations.csv"):
            body = {k: row[k] for k in ("facility_id", "material_code", "period_start", "period_end")}
            r = client.post("/api/v1/reconciliations", json=body)
            got = r.json() if r.status_code == 201 else {"status": f"HTTP {r.status_code}"}
            checks.append(
                ReconciliationCheck(
                    scenario=row["scenario"],
                    facility_id=row["facility_id"],
                    material_code=row["material_code"],
                    expected_status=row["expected_status"],
                    status=got["status"],
                    expected_variance_kg=_dec(row["expected_variance_kg"]),
                    variance_kg=_dec(got.get("variance_kg")),
                    expected_tolerance_kg=Decimal(row["expected_tolerance_kg"]),
                    tolerance_kg=_dec(got.get("tolerance_kg")),
                )
            )
    app.state.engine.dispose()
    return checks


# ---------------------------------------------------------------- performance (NFR-08)

PERF_HEADER = "source_record_id,facility_id,material_name,event_type,quantity,unit,event_timestamp,batch_id\n"
PERF_MATERIALS = ("Plastic film", "LDPE film", "Recycled resin", "PCR resin", "Glass cullet")  # the last is unknown
PERF_TYPES = ("RECEIPT", "PRODUCTION", "SHIPMENT", "LOSS", "INVENTORY_ADJUSTMENT", "CONSUMPTION", "TRANSFER")
PERF_UNITS = ("kg", "kg", "lb", "lbs", "tons")  # tons is unsupported


def perf_csv(rows: int = PERF_ROWS, seed: int = PERF_SEED) -> bytes:
    """A seeded synthetic CSV, built in memory and never written to disk.

    Mix: unknown materials, unknown event types, unsupported units, and negative quantities on any type.
    """
    rng = random.Random(seed)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    out = io.StringIO()
    out.write(PERF_HEADER)
    for n in range(1, rows + 1):
        quantity = Decimal(rng.randint(1, 500_000)) / 100
        if rng.random() < 0.1:
            quantity = -quantity
        at = start + timedelta(minutes=rng.randint(0, 30 * 24 * 60))
        out.write(
            f"PERF-{n:05d},FAC-{rng.randint(30, 39)},{rng.choice(PERF_MATERIALS)},{rng.choice(PERF_TYPES)},"
            f"{quantity},{rng.choice(PERF_UNITS)},{at.strftime('%Y-%m-%dT%H:%M:%SZ')},PB-{rng.randint(1, 200)}\n"
        )
    return out.getvalue().encode()


@dataclass
class PerfRun:
    label: str
    seconds: float
    received: int
    accepted: int
    quarantined: int
    flagged: int
    duplicates: int
    new_events: int


@dataclass
class Performance:
    database: str
    runs: list[PerfRun]


def performance(database_url: str, reset: bool = False) -> Performance:
    """Import the 10,000-row CSV through the API twice and time each request."""
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select, text

    from app.database.tables import Base, IngestionRunRow, MaterialEventRow
    from app.main import create_app

    app = create_app(database_url, init_attempts=1)
    engine = app.state.engine
    if reset:
        Base.metadata.drop_all(engine)
    data = perf_csv()
    runs = []
    with TestClient(app) as client:
        with app.state.sessionmaker() as s:
            if s.scalar(select(func.count()).select_from(IngestionRunRow)):
                raise SystemExit(
                    "The database already has ingestion runs, so the timing would not be comparable. "
                    "Use an empty database, or pass --reset to drop and recreate RecyTrack's tables in it."
                )
            version = s.scalar(text("SELECT sqlite_version()" if engine.dialect.name == "sqlite" else "SELECT version()"))
        database = f"{engine.dialect.name} {version}"

        def events() -> int:
            with app.state.sessionmaker() as s:
                return s.scalar(select(func.count()).select_from(MaterialEventRow))

        for label in ("First import", "Re-import"):
            before = events()
            start = time.perf_counter()
            r = client.post("/api/v1/ingestion/csv", files={"file": ("perf_10000.csv", data, "text/csv")})
            seconds = time.perf_counter() - start
            r.raise_for_status()
            run = r.json()
            runs.append(
                PerfRun(label, seconds, run["received_count"], run["accepted_count"], run["quarantined_count"],
                        run["flagged_count"], run["duplicate_count"], events() - before)
            )
    engine.dispose()
    return Performance(database, runs)


# ---------------------------------------------------------------- report


def pct(value: Decimal | None) -> str:
    """One decimal, but never shows 100.0% or 0.0% unless the value is exactly that."""
    if value is None:
        return "n/a"
    shown = (value * 100).quantize(Decimal("0.1"))
    if shown == 100 and value != 1:
        return "99.9%"
    if shown == 0 and value != 0:
        return "<0.1%"
    return f"{shown}%"


def _git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                                check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return commit + (" (with uncommitted changes)" if dirty else "")


def environment() -> str:
    return (
        f"Python {platform.python_version()}, {platform.platform()}, {os.cpu_count()} logical CPUs"
        + (f", {platform.processor()}" if platform.processor() else "")
    )


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def _kg(value: Decimal | None) -> str:
    return "—" if value is None else f"{value.normalize():f}"


def render(quality: list[SetQuality], idem: list[Idempotency], recon: list[ReconciliationCheck],
           perf: Performance | None, failures: list[str]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Measured results",
        "",
        f"Generated by `python -m scripts.measure` on {now} · commit {_git_commit()} · {environment()}.",
        "Do not edit by hand: re-run the script.",
        "",
        "## Labeled-set quality",
        "",
        HONESTY_NOTE,
        "",
        "A row is *faulty* if its labeled status is not `ACCEPTED`. *Detected* = faulty and the pipeline did not accept "
        "it. *False positive* = clean but not accepted. *Exact match* = the status and the set of rule codes both "
        "equal the label.",
        "",
    ]
    lines += _table(
        ["Set", "Rows", "Faulty", "Detected", "Detection rate", "Clean", "False positives", "False-positive rate",
         "Exact matches"],
        [
            [f"**{q.name}**" if q.name == "Total" else f"`{q.name}`", q.rows, q.faulty, q.detected,
             pct(q.detection_rate), q.clean, q.false_positives, pct(q.false_positive_rate), f"{q.exact} / {q.rows}"]
            for q in quality
        ],
    )
    total = quality[-1]
    lines += ["", "### Per rule (all sets)", "", "Rows whose label contains the rule code vs rows where the pipeline "
              "raised it.", ""]
    codes = sorted(set(total.expected_by_rule) | set(total.found_by_rule))
    lines += _table(
        ["Rule", "Expected", "Found", "Equal"],
        [[c, total.expected_by_rule[c], total.found_by_rule[c],
          "yes" if total.expected_by_rule[c] == total.found_by_rule[c] else "**no**"] for c in codes],
    )

    lines += ["", "## Idempotency (VAL-007)", "",
              "Each labeled set imported twice into the same repository; the numbers are for the second import. "
              "A row without a `source_record_id` has no stable key, so it is re-evaluated (documented behavior) "
              "and counted separately.", ""]
    lines += _table(
        ["Set", "Received", "Duplicates", "Rows with a key", "New events", "of which rows without a key", "Pass"],
        [[f"`{i.name}`", i.received, i.duplicates, i.rows_with_key, i.new_events, i.new_events_without_key,
          "yes" if i.passed else "**no**"] for i in idem],
    )

    matched = sum(c.matches for c in recon)
    lines += ["", "## Reconciliation scenarios", "",
              f"`reconciliation_scenarios.csv` imported through the API (in-memory SQLite), then every row of "
              f"`expected_reconciliations.csv` run: **{matched} / {len(recon)}** match status, variance and tolerance.",
              ""]
    lines += _table(
        ["Scenario", "Facility", "Material", "Expected status", "Status", "Expected variance kg", "Variance kg",
         "Expected tolerance kg", "Tolerance kg", "Match"],
        [[c.scenario, c.facility_id, c.material_code, c.expected_status, c.status, _kg(c.expected_variance_kg),
          _kg(c.variance_kg), _kg(c.expected_tolerance_kg), _kg(c.tolerance_kg), "yes" if c.matches else "**no**"]
         for c in recon],
    )

    lines += ["", "## Performance (NFR-08, target < 30 s for 10,000 rows)", ""]
    if perf is None:
        lines += ["Not measured in this run (no `--database-url`)."]
    else:
        lines += [
            f"A seeded {PERF_ROWS:,}-row synthetic CSV (seed {PERF_SEED}, built in memory, never saved) imported through "
            f"`POST /api/v1/ingestion/csv` twice. Database: {perf.database}. Machine: {environment()}. "
            "Wall-clock seconds for the whole request, measured once; they depend on the machine and are not a "
            "production guarantee.",
            "",
        ]
        lines += _table(
            ["Run", "Seconds", "Received", "Accepted", "Quarantined", "Flagged", "Duplicates", "New events"],
            [[r.label, f"{r.seconds:.2f}", f"{r.received:,}", f"{r.accepted:,}", f"{r.quarantined:,}",
              f"{r.flagged:,}", f"{r.duplicates:,}", f"{r.new_events:,}"] for r in perf.runs],
        )

    lines += ["", "## Checks", ""]
    lines += [f"- **FAILED:** {f}" for f in failures] or ["- All exact-match, idempotency and reconciliation checks "
                                                         "passed (100%)."]
    return "\n".join(lines) + "\n"


def failures(quality: list[SetQuality], idem: list[Idempotency], recon: list[ReconciliationCheck]) -> list[str]:
    out = [m for q in quality[:-1] for m in q.mismatches]
    out += [f"idempotency {i.name}: {i.new_events - i.new_events_without_key} new events with a key, "
            f"{i.duplicates} duplicates of {i.rows_with_key} keyed rows" for i in idem if not i.passed]
    out += [f"reconciliation {c.scenario}: expected {c.expected_status} {_kg(c.expected_variance_kg)} / "
            f"{_kg(c.expected_tolerance_kg)}, got {c.status} {_kg(c.variance_kg)} / {_kg(c.tolerance_kg)}"
            for c in recon if not c.matches]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--database-url", help="also time a 10,000-row import on this (empty) database")
    parser.add_argument("--reset", action="store_true", help="drop and recreate RecyTrack's tables first")
    parser.add_argument("--out", type=Path, help="write the Markdown report to this file")
    args = parser.parse_args(argv)

    # Request and run logs would drown the report; warnings and errors still show.
    previous_level = os.environ.get("LOG_LEVEL")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    try:
        quality = labeled_quality()
        idem = idempotency()
        recon = reconciliation()
        perf = performance(args.database_url, args.reset) if args.database_url else None
    finally:
        if previous_level is None:
            os.environ.pop("LOG_LEVEL", None)
    failed = failures(quality, idem, recon)

    report = render(quality, idem, recon, perf, failed)
    sys.stdout.flush()
    sys.stdout.buffer.write(report.encode("utf-8"))  # UTF-8 even on a Windows console code page
    sys.stdout.buffer.flush()
    if args.out:
        args.out.write_text(report, encoding="utf-8", newline="\n")
        print(f"\nWrote {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
