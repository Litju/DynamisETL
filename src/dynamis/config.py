"""Configuration surface for machine-local roots.

Absolute scientific-data and database-state roots are machine-local facts. They
are read from the environment (or a git-ignored ``.env``) and are never
hard-coded in application modules.

Resolution order when no explicit mapping is supplied:

1. ``.env`` at the repository root (git-ignored, optional, developer convenience)
2. the process environment (always wins)
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ENV_DATASET_ROOT = "DYNAMIS_DATASET_ROOT"
ENV_DATABASE_ROOT = "DYNAMIS_DATABASE_ROOT"
ENV_DUCKDB_PATH = "DYNAMIS_DUCKDB_PATH"
ENV_DB_SCHEMA = "DYNAMIS_DB_SCHEMA"
ENV_POSTGRES_URL = "POSTGRES_URL"
ENV_TEST_POSTGRES_URL = "DYNAMIS_TEST_POSTGRES_URL"

DEFAULT_DB_SCHEMA = "dynamis"
DUCKDB_SUBDIR = "duckdb"
DUCKDB_FILENAME = "dynamis.duckdb"
POSTGRES_SUBDIR = "postgres"

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_SCHEMA_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ConfigurationError(RuntimeError):
    """Raised when required machine-local configuration is absent or invalid."""


def repository_root() -> Path:
    """Repository root derived from this module's location (never hard-coded)."""
    return Path(__file__).resolve().parents[2]


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping.

    Supports ``KEY=VALUE`` lines, ``#`` comments, blank lines and optional single
    or double quoting. It performs no interpolation and does not mutate the
    process environment, so callers stay in control of resolution order.
    """
    env_path = repository_root() / ".env" if path is None else path
    if not env_path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolved_environ(env: Mapping[str, str] | None = None) -> dict[str, str]:
    if env is not None:
        return dict(env)
    merged = load_env_file()
    merged.update(os.environ)
    return merged


def _schema_from_values(values: Mapping[str, str]) -> str:
    schema = values.get(ENV_DB_SCHEMA, DEFAULT_DB_SCHEMA).strip() or DEFAULT_DB_SCHEMA
    if not _SCHEMA_NAME.match(schema):
        raise ConfigurationError(
            f"{ENV_DB_SCHEMA}={schema!r} is not a valid PostgreSQL schema name"
        )
    return schema


def resolve_db_schema(env: Mapping[str, str] | None = None) -> str:
    """Resolve the PostgreSQL schema without requiring filesystem roots.

    Alembic and the migration bootstrap need only the schema name, so importing
    this must not require ``DYNAMIS_DATASET_ROOT`` to be configured.
    """
    return _schema_from_values(resolved_environ(env))


class Settings(BaseModel):
    """Resolved runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_root: Path
    database_root: Path
    duckdb_path: Path
    db_schema: str = Field(default=DEFAULT_DB_SCHEMA, pattern=r"^[a-z][a-z0-9_]*$")
    postgres_url: str | None = None
    test_postgres_url: str | None = None

    def require_postgres_url(self) -> str:
        if not self.postgres_url:
            raise ConfigurationError(
                f"{ENV_POSTGRES_URL} is not set. Copy .env.example to .env and provide the "
                "PostgreSQL credentials, or export the variable before running migrations."
            )
        return self.postgres_url

    @classmethod
    def from_environ(cls, env: Mapping[str, str] | None = None) -> Settings:
        values = resolved_environ(env)
        dataset_root = values.get(ENV_DATASET_ROOT, "").strip()
        database_root = values.get(ENV_DATABASE_ROOT, "").strip()
        missing = [
            name
            for name, value in (
                (ENV_DATASET_ROOT, dataset_root),
                (ENV_DATABASE_ROOT, database_root),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "missing required environment configuration: "
                + ", ".join(missing)
                + ". Copy .env.example to .env (git-ignored) or export these variables. "
                "Scientific data and database state must live outside the repository."
            )

        database_path = Path(database_root)
        duckdb_value = values.get(ENV_DUCKDB_PATH, "").strip()
        duckdb_path = (
            Path(duckdb_value) if duckdb_value else database_path / DUCKDB_SUBDIR / DUCKDB_FILENAME
        )

        schema = _schema_from_values(values)

        return cls(
            dataset_root=Path(dataset_root),
            database_root=database_path,
            duckdb_path=duckdb_path,
            db_schema=schema,
            postgres_url=values.get(ENV_POSTGRES_URL) or None,
            test_postgres_url=values.get(ENV_TEST_POSTGRES_URL) or None,
        )


def settings(env: Mapping[str, str] | None = None) -> Settings:
    """Resolve settings from the optional ``.env`` file layered under the environment."""
    return Settings.from_environ(env)


def postgres_subdir(database_root: Path) -> Path:
    """Host directory bind-mounted at ``/var/lib/postgresql`` for PostgreSQL 18."""
    return database_root / POSTGRES_SUBDIR
