"""DynamisData analytical API (FastAPI over PostgreSQL gold/metadata + Parquet)."""

from __future__ import annotations

from dynamis.serving.app import (
    API_VERSION,
    PostgresServingBackend,
    ServingBackend,
    create_app,
    get_backend,
)

__all__ = [
    "API_VERSION",
    "PostgresServingBackend",
    "ServingBackend",
    "create_app",
    "get_backend",
]
