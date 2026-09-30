"""PostgreSQL control-plane access with transaction-local schema selection."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, Connection, make_url

from dynamis.config import ConfigurationError, Settings

ENV_POSTGRES_URL = "POSTGRES_URL"


def control_plane_engine(settings: Settings, url: str | None = None) -> Engine:
    """Create an engine that binds each transaction to the configured schema."""
    target = url or settings.postgres_url
    if not target:
        raise ConfigurationError(
            "POSTGRES_URL is not configured; set it in .env to persist control-plane metadata"
        )
    parsed: URL = make_url(target)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    engine = create_engine(
        parsed,
        pool_pre_ping=True,
        pool_size=_positive_int("DYNAMIS_DB_POOL_SIZE", 4),
        max_overflow=_positive_int("DYNAMIS_DB_MAX_OVERFLOW", 4),
        pool_timeout=_positive_int("DYNAMIS_DB_POOL_TIMEOUT", 30),
        future=True,
    )

    @event.listens_for(engine, "begin")
    def _set_schema(connection: Connection) -> None:
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{settings.db_schema}", public')

    return engine


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name}={raw!r} must be an integer") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return value
