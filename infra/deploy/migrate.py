"""Apply and verify Alembic migrations on an isolated Vercel Neon environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from dynamis.config import ENV_MIGRATION_POSTGRES_URL, resolved_environ
from dynamis.deployment import DeploymentError


def _database_target(url: str) -> str:
    host = urlparse(url).hostname or ""
    if not host.endswith(".neon.tech"):
        raise DeploymentError("migration URL must target the Vercel-managed Neon database")
    endpoint = re.sub(r"-pooler(?=\.)", "", host, count=1)
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def _sha(root: Path) -> str:
    value = os.environ.get("DYNAMIS_CODE_GIT_SHA", "").strip()
    if not value:
        value = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise DeploymentError("DYNAMIS_CODE_GIT_SHA must be a 40-character lowercase Git SHA")
    return value


def run(apply: bool) -> int:
    root = Path(__file__).resolve().parents[2]
    values = resolved_environ()
    environment = values.get("DYNAMIS_DEPLOY_ENV", "")
    if environment not in {"preview", "production"}:
        raise DeploymentError("set DYNAMIS_DEPLOY_ENV to preview or production")
    if values.get("VERCEL_ENV") and values["VERCEL_ENV"] != environment:
        raise DeploymentError("DYNAMIS_DEPLOY_ENV does not match the Vercel environment")
    migration_url = values.get(ENV_MIGRATION_POSTGRES_URL, "").strip()
    if not migration_url:
        raise DeploymentError(f"{ENV_MIGRATION_POSTGRES_URL} is required")
    target = _database_target(migration_url)

    if environment == "production":
        evidence = values.get("DYNAMIS_RELEASE_EVIDENCE", "").strip()
        if not evidence:
            raise DeploymentError("Production migration requires completed Preview evidence")
        subprocess.run(
            [sys.executable, "-m", "infra.deploy.release_gate", evidence, "--git-sha", _sha(root)],
            cwd=root,
            check=True,
        )
        preview = json.loads(Path(evidence).read_text(encoding="utf-8"))
        if preview.get("database_target_sha256") == target:
            raise DeploymentError("Production and Preview must use isolated Neon endpoints")

    if apply:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True)
    subprocess.run(
        [sys.executable, str(root / "infra/deploy/check_migrations.py")], cwd=root, check=True
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="check current Alembic state only")
    group.add_argument("--apply", action="store_true", help="upgrade to head, then verify")
    args = parser.parse_args(argv)
    try:
        return run(args.apply)
    except (DeploymentError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"migration gate blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
