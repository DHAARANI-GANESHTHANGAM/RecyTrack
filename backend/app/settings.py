"""Runtime settings read from environment variables (NFR-05: no secrets in code)."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///./recytrack.db"


def database_url() -> str:
    """DATABASE_URL from the environment.

    PostgreSQL is the target database (docker-compose sets it). Without the
    variable the app falls back to a local SQLite file so it can be tried
    without installing anything.
    """
    url = os.environ.get("DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL
    # Accept the common postgres:// and postgresql:// forms and use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class SourceSettings:
    """How the API reaches the simulated source (M7, NFR-02)."""

    url: str = "http://127.0.0.1:8001"
    attempts: int = 3
    backoff_s: float = 0.5
    timeout_s: float = 5.0


def _env_number(name: str, default, cast, minimum):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        value = None
    if value is None or value < minimum:
        raise ValueError(f"{name}={raw!r} is not valid; use a number >= {minimum}.")
    return value


def source_settings() -> SourceSettings:
    """SIMULATED_SOURCE_URL, SOURCE_RETRY_ATTEMPTS, SOURCE_RETRY_BACKOFF_S and SOURCE_TIMEOUT_S from the environment."""
    defaults = SourceSettings()
    return SourceSettings(
        url=(os.environ.get("SIMULATED_SOURCE_URL", "").strip() or defaults.url).rstrip("/"),
        attempts=_env_number("SOURCE_RETRY_ATTEMPTS", defaults.attempts, int, 1),
        backoff_s=_env_number("SOURCE_RETRY_BACKOFF_S", defaults.backoff_s, float, 0),
        timeout_s=_env_number("SOURCE_TIMEOUT_S", defaults.timeout_s, float, 0.1),
    )
