"""Verify Neon is at the explicit Alembic head and has serving tables."""

from __future__ import annotations

import argparse
import json
import sys

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import ForeignKeyConstraint, create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from dynamis.config import ENV_MIGRATION_POSTGRES_URL, resolve_db_schema, resolved_environ
from dynamis.gold.build import MART_NAMES
from dynamis.gold.publish import resolve_gold_schema
from dynamis.storage.tables import Base


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-gold", action="store_true", help="also require every published Gold serving mart"
    )
    args = parser.parse_args()
    values = resolved_environ()
    url = values.get(ENV_MIGRATION_POSTGRES_URL, "").strip()
    if not url:
        print(
            f"{ENV_MIGRATION_POSTGRES_URL} is required for migration verification", file=sys.stderr
        )
        return 2
    config = Config("alembic.ini")
    expected = set(ScriptDirectory.from_config(config).get_heads())
    schema = resolve_db_schema(values)
    parsed_url = make_url(url)
    if parsed_url.drivername in {"postgres", "postgresql"}:
        parsed_url = parsed_url.set(drivername="postgresql+psycopg")
    engine = create_engine(parsed_url, poolclass=NullPool)
    missing_tables: list[str] = []
    missing_constraints: list[str] = []
    missing_foreign_keys: list[str] = []
    missing_indexes: list[str] = []
    missing_gold: list[str] = []
    try:
        with engine.connect() as connection:
            current = set(
                MigrationContext.configure(
                    connection, opts={"version_table_schema": schema}
                ).get_current_heads()
            )
            inspector = inspect(connection)
            actual_tables = set(inspector.get_table_names(schema=schema))
            required_tables = {table.name for table in Base.metadata.tables.values()}
            missing_tables = sorted(required_tables - actual_tables)
            for table in Base.metadata.tables.values():
                if table.name not in actual_tables:
                    continue
                actual_indexes = {
                    item["name"] for item in inspector.get_indexes(table.name, schema=schema)
                }
                missing_indexes.extend(
                    f"{table.name}.{index.name}"
                    for index in table.indexes
                    if index.name and index.name not in actual_indexes
                )
                actual_constraints = {
                    item.get("name")
                    for getter in (
                        inspector.get_check_constraints,
                        inspector.get_unique_constraints,
                    )
                    for item in getter(table.name, schema=schema)
                    if item.get("name")
                }
                primary_key = inspector.get_pk_constraint(table.name, schema=schema).get("name")
                if primary_key:
                    actual_constraints.add(primary_key)
                missing_constraints.extend(
                    f"{table.name}.{constraint.name}"
                    for constraint in table.constraints
                    if (
                        constraint.name
                        and not isinstance(constraint, ForeignKeyConstraint)
                        and constraint.name not in actual_constraints
                    )
                )
                expected_fks = {
                    (
                        tuple(element.parent.name for element in constraint.elements),
                        constraint.elements[0].column.table.name,
                        tuple(element.column.name for element in constraint.elements),
                    )
                    for constraint in table.foreign_key_constraints
                }
                actual_fks = {
                    (
                        tuple(item.get("constrained_columns") or ()),
                        item.get("referred_table"),
                        tuple(item.get("referred_columns") or ()),
                    )
                    for item in inspector.get_foreign_keys(table.name, schema=schema)
                }
                missing_foreign_keys.extend(
                    f"{table.name}.{columns}->{target}{target_columns}"
                    for columns, target, target_columns in expected_fks - actual_fks
                )
            if args.require_gold:
                gold_schema = resolve_gold_schema()
                gold_tables = set(inspector.get_table_names(schema=gold_schema))
                missing_gold = sorted(set(MART_NAMES) - gold_tables)
    finally:
        engine.dispose()
    if (
        current != expected
        or missing_tables
        or missing_constraints
        or missing_foreign_keys
        or missing_indexes
        or missing_gold
    ):
        print(
            json.dumps(
                {
                    "current": sorted(current),
                    "expected": sorted(expected),
                    "missing_tables": missing_tables,
                    "missing_constraints": sorted(missing_constraints),
                    "missing_foreign_keys": sorted(missing_foreign_keys),
                    "missing_indexes": sorted(missing_indexes),
                    "missing_gold_tables": missing_gold,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "schema": schema,
                "alembic_heads": sorted(current),
                "required_tables": len(Base.metadata.tables),
                "required_indexes": sum(
                    bool(index.name)
                    for table in Base.metadata.tables.values()
                    for index in table.indexes
                ),
                "gold_tables": list(MART_NAMES) if args.require_gold else [],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
