"""Runtime settings read from environment variables (NFR-05: no secrets in code)."""
from __future__ import annotations

import os

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
