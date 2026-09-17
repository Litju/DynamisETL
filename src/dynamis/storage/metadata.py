"""SQLAlchemy metadata authority.

One :class:`~sqlalchemy.MetaData` with one naming convention, shared by the
declarative models in :mod:`dynamis.storage.tables`, Alembic autogenerate and
the migration bootstrap helper.

Tables are intentionally *unqualified*: the target PostgreSQL schema is applied
at runtime through the connection ``search_path`` (see
:mod:`dynamis.storage.migration_support`), so the same metadata works against a
developer schema, a test schema and CI without import-time environment reads.
"""

from __future__ import annotations

from sqlalchemy import MetaData

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


def build_metadata() -> MetaData:
    """Return the fully-populated metadata, importing the table module once."""
    from dynamis.storage import tables

    expected = tables.EXPECTED_TABLE_NAMES
    actual = frozenset(metadata.tables)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise RuntimeError(
            "metadata/table drift detected: "
            f"missing={missing} unexpected={unexpected}. "
            "Update EXPECTED_TABLE_NAMES and the bootstrap migration together."
        )
    return metadata
