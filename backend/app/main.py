"""FastAPI application. Run with:  uvicorn app.main:app --reload

Interactive API docs are served at /docs (FR-18).
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.routes import router
from app.database.db import init_db, make_engine, make_sessionmaker
from app.logging_config import configure_logging, request_id_var
from app.settings import database_url, source_settings

log = logging.getLogger("recytrack")
request_log = logging.getLogger("recytrack.request")

# Accept a caller's X-Request-ID only if it is short and plain, so it cannot inject text into logs.
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

DB_UNAVAILABLE = "Database unavailable. Check that PostgreSQL is running and DATABASE_URL is set, then retry."


def create_app(db_url: str | None = None, init_attempts: int = 5) -> FastAPI:
    configure_logging()
    engine = make_engine(db_url or database_url())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(engine, attempts=init_attempts)
        yield
        engine.dispose()

    app = FastAPI(
        title="RecyTrack API",
        version="0.4.0",
        description="Recycling data quality and material traceability. All demo data is synthetic.",
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.source_settings = source_settings()
    app.state.source_transport = None  # tests put an httpx transport here to reach the simulator in-process
    app.include_router(router)

    @app.middleware("http")
    async def request_id_and_access_log(request: Request, call_next):
        """Read or create X-Request-ID, return it, and log one line per request (NFR-02)."""
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # The path only: query strings can carry filter values.
            request_log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    "request_id": request_id,
                },
            )
            request_id_var.reset(token)

    @app.get("/health", tags=["health"])
    def health():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)
        return {"status": "ok", "database": "ok"}

    # FR-19: actionable errors without leaking connection strings or SQL.
    @app.exception_handler(OperationalError)
    async def _db_down(request: Request, exc: OperationalError):
        log.error("Database error on %s %s: %s", request.method, request.url.path, exc.__class__.__name__)
        return JSONResponse({"detail": DB_UNAVAILABLE}, status_code=503)

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError):
        # The class name only: the exception text can contain SQL parameters, i.e. row values.
        log.error("Database error on %s %s: %s", request.method, request.url.path, exc.__class__.__name__)
        return JSONResponse({"detail": "A database error occurred. The request was not saved; retry it."}, status_code=500)

    return app


app = create_app()
