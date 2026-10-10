"""FastAPI application. Run with:  uvicorn app.main:app --reload

Interactive API docs are served at /docs (FR-18).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.api.routes import router
from app.database.db import init_db, make_engine, make_sessionmaker
from app.settings import database_url

log = logging.getLogger("recytrack")

DB_UNAVAILABLE = "Database unavailable. Check that PostgreSQL is running and DATABASE_URL is set, then retry."


def create_app(db_url: str | None = None, init_attempts: int = 5) -> FastAPI:
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
    app.include_router(router)

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
        log.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "A database error occurred. The request was not saved; retry it."}, status_code=500)

    return app


app = create_app()
