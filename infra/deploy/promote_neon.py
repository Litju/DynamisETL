"""Copy a verified Preview Neon database to Production and write a promotion receipt."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from infra.deploy.release_gate import check_evidence
from infra.deploy.seed import _database_target, _sha
from infra.deploy.verify_artifact_receipt import compare_receipts
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from dynamis.config import resolve_db_schema
from dynamis.deployment import DeploymentError, rights_allowlist_sha256
from dynamis.gold.publish import resolve_gold_schema
from dynamis.storage.atomic import atomic_write_text, sha256_file


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise DeploymentError(f"{name} is required for Neon promotion")
    return value


def _connection(url: str) -> tuple[dict[str, str], str]:
    parsed = make_url(url)
    if not parsed.host or not parsed.host.endswith(".neon.tech"):
        raise DeploymentError("Neon promotion accepts direct Neon PostgreSQL endpoints only")
    if "-pooler" in parsed.host:
        raise DeploymentError("pg_dump and pg_restore require direct, unpooled Neon endpoints")
    if not parsed.database or not parsed.username:
        raise DeploymentError("Neon promotion connection URL is incomplete")
    env = os.environ.copy()
    for name in (
        "DATABASE_URL",
        "DATABASE_URL_UNPOOLED",
        "DYNAMIS_MIGRATION_POSTGRES_URL",
        "DYNAMIS_PREVIEW_DATABASE_URL",
        "DYNAMIS_PRODUCTION_DATABASE_URL",
        "POSTGRES_URL",
    ):
        env.pop(name, None)
    env.update(
        {
            "PGHOST": parsed.host,
            "PGPORT": str(parsed.port or 5432),
            "PGDATABASE": parsed.database,
            "PGUSER": parsed.username,
            "PGPASSWORD": parsed.password or "",
            "PGSSLMODE": str(parsed.query.get("sslmode", "require")),
        }
    )
    return env, parsed.database


def _sqlalchemy_url(url: str):
    parsed = make_url(url)
    if parsed.drivername in {"postgres", "postgresql"}:
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed


def _heads(url: str, schema: str) -> tuple[str, ...]:
    engine = sa.create_engine(_sqlalchemy_url(url), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return tuple(
                sorted(
                    MigrationContext.configure(
                        connection, opts={"version_table_schema": schema}
                    ).get_current_heads()
                )
            )
    finally:
        engine.dispose()


def _expected_heads() -> tuple[str, ...]:
    return tuple(sorted(ScriptDirectory.from_config(Config("alembic.ini")).get_heads()))


def database_counts(url: str, gold_schema: str) -> dict[str, Any]:
    """Count user tables and rows exactly, with per-table Gold evidence."""
    engine = sa.create_engine(_sqlalchemy_url(url), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            tables = connection.execute(
                sa.text(
                    """SELECT table_schema, table_name
                       FROM information_schema.tables
                       WHERE table_type = 'BASE TABLE'
                         AND table_schema NOT IN ('pg_catalog', 'information_schema')
                         AND table_schema NOT LIKE 'pg_toast%'
                       ORDER BY table_schema, table_name"""
                )
            ).all()
            quote = connection.dialect.identifier_preparer.quote
            table_rows = {
                f"{schema}.{table}": int(
                    connection.execute(
                        sa.text(f"SELECT count(*) FROM {quote(schema)}.{quote(table)}")
                    ).scalar_one()
                )
                for schema, table in tables
            }
    finally:
        engine.dispose()
    gold_rows = {
        name: rows for name, rows in table_rows.items() if name.startswith(f"{gold_schema}.")
    }
    return {
        "table_count": len(table_rows),
        "row_count": sum(table_rows.values()),
        "gold_table_count": len(gold_rows),
        "gold_row_count": sum(gold_rows.values()),
        "table_rows": table_rows,
        "gold_table_rows": gold_rows,
    }


def _identity() -> dict[str, Any]:
    preview_project = _env("DYNAMIS_PREVIEW_NEON_PROJECT_ID")
    preview_branch = _env("DYNAMIS_PREVIEW_NEON_BRANCH_ID")
    production_project = _env("DYNAMIS_PRODUCTION_NEON_PROJECT_ID")
    production_branch = _env("DYNAMIS_PRODUCTION_NEON_BRANCH_ID")
    if (preview_project, preview_branch) == (production_project, production_branch):
        raise DeploymentError("Preview and Production Neon project/branch IDs must be distinct")
    return {
        "preview": {"project_id": preview_project, "branch_id": preview_branch},
        "production": {"project_id": production_project, "branch_id": production_branch},
    }


def _blob_receipts(preview_path: Path, production_path: Path, git_sha: str) -> dict[str, Any]:
    failures = compare_receipts(preview_path, production_path, git_sha)
    if failures:
        raise DeploymentError(
            "Preview/Production Blob receipt parity failed: " + "; ".join(failures)
        )
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    return {
        "passed": True,
        "object_count": preview["object_count"],
        "preview_receipt_sha256": sha256_file(preview_path),
        "production_receipt_sha256": sha256_file(production_path),
    }


def _run(args: list[str], env: dict[str, str], *, stdout=None) -> None:
    completed = subprocess.run(
        args,
        env=env,
        stdout=subprocess.PIPE if stdout is None else stdout,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise DeploymentError(
            f"{Path(args[0]).name} failed with exit code {completed.returncode}; "
            "PostgreSQL command output was suppressed to protect connection details"
        )


def _preflight(
    preview_receipt: Path,
    production_receipt: Path,
) -> tuple[str, str, dict[str, Any], dict[str, str], str, tuple[str, ...], dict[str, Any]]:
    if os.environ.get("DYNAMIS_DEPLOY_ENV") != "production":
        raise DeploymentError("set DYNAMIS_DEPLOY_ENV=production before Neon promotion")
    git_sha = _sha()
    actual_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if actual_sha != git_sha:
        raise DeploymentError("DYNAMIS_CODE_GIT_SHA must match the checked-out merged-main SHA")
    expected_heads = _expected_heads()
    if len(expected_heads) != 1:
        raise DeploymentError("Neon promotion requires exactly one Alembic head")
    schema = resolve_db_schema()
    gold_schema = resolve_gold_schema()
    evidence = _env("DYNAMIS_RELEASE_EVIDENCE")
    failures = check_evidence(Path(evidence), git_sha)
    if failures:
        raise DeploymentError("Preview release gate failed: " + "; ".join(failures))
    evidence_data = json.loads(Path(evidence).read_text(encoding="utf-8"))
    evidence_receipt = Path(evidence_data["artifact_receipt"])
    if not evidence_receipt.is_absolute():
        evidence_receipt = Path(evidence).resolve().parent / evidence_receipt
    if evidence_receipt.resolve() != preview_receipt.resolve():
        raise DeploymentError("Preview Blob receipt must match the accepted Preview evidence")
    parity = _blob_receipts(preview_receipt, production_receipt, git_sha)
    if evidence_data.get("database_target_sha256") == _database_target(
        _env("DYNAMIS_PRODUCTION_DATABASE_URL")
    ):
        raise DeploymentError("Preview and Production Neon endpoints must be isolated")
    preview_url = _env("DYNAMIS_PREVIEW_DATABASE_URL")
    production_url = _env("DYNAMIS_PRODUCTION_DATABASE_URL")
    _connection(preview_url)
    _connection(production_url)
    if _database_target(preview_url) == _database_target(production_url):
        raise DeploymentError("Preview and Production Neon endpoints must be isolated")
    identity = _identity()
    return (
        git_sha,
        schema,
        identity,
        {
            "preview": preview_url,
            "production": production_url,
        },
        gold_schema,
        expected_heads,
        parity,
    )


def promote(
    *,
    apply: bool,
    preview_receipt: Path,
    production_receipt: Path,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    git_sha, schema, identity, urls, gold_schema, expected_heads, parity = _preflight(
        preview_receipt, production_receipt
    )
    source_heads = _heads(urls["preview"], schema)
    if source_heads != expected_heads:
        raise DeploymentError("Preview Neon is not at the checked-out Alembic head")
    preview_counts = database_counts(urls["preview"], gold_schema)
    production_before_counts = database_counts(urls["production"], gold_schema)
    if not apply:
        return {
            "environment": "production",
            "git_sha": git_sha,
            "neon": identity,
            "alembic_head": expected_heads[0],
            "preview_counts": preview_counts,
            "production_before_counts": production_before_counts,
            "blob_receipt_parity": parity,
            "rights_allowlist_sha256": rights_allowlist_sha256(),
        }

    pg_dump = shutil.which(os.environ.get("PG_DUMP", "pg_dump"))
    pg_restore = shutil.which(os.environ.get("PG_RESTORE", "pg_restore"))
    if not pg_dump or not pg_restore:
        raise DeploymentError("pg_dump and pg_restore must be installed for Neon promotion")
    source_env, source_database = _connection(urls["preview"])
    target_env, target_database = _connection(urls["production"])
    with tempfile.TemporaryDirectory(prefix="dynamis-neon-promotion-") as directory:
        dump_path = Path(directory) / "preview.dump"
        _run(
            [
                pg_dump,
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                source_database,
                "--file",
                str(dump_path),
            ],
            source_env,
        )
        dump_sha256 = sha256_file(dump_path)
        _run([pg_restore, "--list", str(dump_path)], source_env, stdout=subprocess.DEVNULL)
        _run(
            [
                pg_restore,
                "--clean",
                "--if-exists",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                target_database,
                str(dump_path),
            ],
            target_env,
        )

    production_heads = _heads(urls["production"], schema)
    if production_heads != expected_heads:
        raise DeploymentError("Production Neon did not restore at the checked-out Alembic head")
    production_counts = database_counts(urls["production"], gold_schema)
    if preview_counts != production_counts:
        raise DeploymentError("Production Neon table, row, or Gold counts differ from Preview")
    receipt: dict[str, Any] = {
        "environment": "production",
        "git_sha": git_sha,
        "neon": identity,
        "alembic_head": expected_heads[0],
        "pg_dump_sha256": dump_sha256,
        "preview_counts": preview_counts,
        "production_before_counts": production_before_counts,
        "production_counts": production_counts,
        "rights_allowlist_sha256": rights_allowlist_sha256(),
        "blob_receipt_parity": parity,
    }
    if receipt_path is None:
        configured = os.environ.get("DYNAMIS_NEON_PROMOTION_RECEIPT", "").strip()
        receipt_path = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2]
            / "output"
            / "deploy"
            / f"neon-promotion-{git_sha}.json"
        )
    atomic_write_text(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="run non-mutating promotion checks")
    mode.add_argument(
        "--apply", action="store_true", help="replace Production with verified Preview"
    )
    parser.add_argument("--preview-blob-receipt", type=Path, required=True)
    parser.add_argument("--production-blob-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        result = promote(
            apply=args.apply,
            preview_receipt=args.preview_blob_receipt,
            production_receipt=args.production_blob_receipt,
            receipt_path=args.receipt,
        )
    except (DeploymentError, OSError, sa.exc.SQLAlchemyError, subprocess.CalledProcessError) as exc:
        print(f"Neon promotion blocked: {exc}", file=sys.stderr)
        return 2
    if args.check:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        path = args.receipt or Path(
            os.environ.get(
                "DYNAMIS_NEON_PROMOTION_RECEIPT",
                Path(__file__).resolve().parents[2]
                / "output"
                / "deploy"
                / f"neon-promotion-{result['git_sha']}.json",
            )
        )
        print(f"Neon promotion receipt: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
