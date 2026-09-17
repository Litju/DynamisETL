"""Shared pytest fixtures.

No fixture requires network access, a real dataset, or a live service. The
PostgreSQL suite is gated on ``DYNAMIS_TEST_POSTGRES_URL`` and skips otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamis.config import ENV_TEST_POSTGRES_URL, Settings, repository_root, resolved_environ
from dynamis.fixtures.synthetic import ModalityFixture, all_fixtures

TEST_DB_SCHEMA = "dynamis_res96_test"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return repository_root()


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Settings rooted entirely inside the pytest temporary directory."""
    database_root = tmp_path / "databases"
    return Settings(
        dataset_root=tmp_path / "datasets",
        database_root=database_root,
        duckdb_path=database_root / "duckdb" / "dynamis.duckdb",
        db_schema=TEST_DB_SCHEMA,
    )


@pytest.fixture
def test_db_schema() -> str:
    """Dedicated schema for PostgreSQL migration tests, isolated from dev state."""
    return TEST_DB_SCHEMA


@pytest.fixture(scope="session")
def fixtures_all() -> tuple[ModalityFixture, ...]:
    return all_fixtures()


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """Live PostgreSQL URL for migration tests; skips when not configured."""
    url = (resolved_environ().get(ENV_TEST_POSTGRES_URL) or "").strip()
    if not url:
        pytest.skip(f"{ENV_TEST_POSTGRES_URL} is not configured; skipping PostgreSQL suite")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url
