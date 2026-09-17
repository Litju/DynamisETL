"""PostgreSQL control-plane access.

The engine applies the target schema through the connection ``search_path`` (the
same mechanism the migrations use), so application code, Alembic and tests all
address the same unqualified tables.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url

from dynamis.config import ConfigurationError, Settings

ENV_POSTGRES_URL = "POSTGRES_URL"


def control_plane_engine(settings: Settings, url: str | None = None) -> Engine:
    """Create an engine bound to the configured schema."""
    target = url or settings.postgres_url
    if not target:
        raise ConfigurationError(
            "POSTGRES_URL is not configured; set it in .env to persist control-plane metadata"
        )
    parsed: URL = make_url(target)
    return create_engine(
        parsed,
        connect_args={"options": f"-c search_path={settings.db_schema},public"},
        pool_pre_ping=True,
        future=True,
    )
