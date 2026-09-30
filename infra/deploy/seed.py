"""Run the pinned, rights-checked preview seed from local Bronze data."""

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

from dynamis.config import ENV_MIGRATION_POSTGRES_URL, ENV_POSTGRES_URL, resolved_environ
from dynamis.deployment import DeploymentError, load_public_seed


def _sha() -> str:
    import re

    value = os.environ.get("DYNAMIS_CODE_GIT_SHA", "").strip()
    if not value:
        value = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise DeploymentError("DYNAMIS_CODE_GIT_SHA must be a 40-character lowercase Git SHA")
    return value


def _database_source_ids() -> set[str]:
    from sqlalchemy import select

    from dynamis.config import settings
    from dynamis.storage.control_plane import control_plane_engine
    from dynamis.storage.tables import DatasetSource

    engine = control_plane_engine(settings())
    try:
        with engine.connect() as connection:
            return set(connection.execute(select(DatasetSource.dataset_id)).scalars().all())
    finally:
        engine.dispose()


def _database_target(url: str) -> str:
    host = urlparse(url).hostname or ""
    if not host.endswith(".neon.tech"):
        raise DeploymentError("deployment database must be the Vercel-managed Neon endpoint")
    endpoint = re.sub(r"-pooler(?=\.)", "", host, count=1)
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def run(
    apply: bool,
    artifact_dataset_id: str | None = None,
    artifact_checksum_sha256: str | None = None,
) -> int:
    values = resolved_environ()
    environment = values.get("DYNAMIS_DEPLOY_ENV", "")
    if environment not in {"preview", "production"}:
        raise DeploymentError("set DYNAMIS_DEPLOY_ENV to preview or production")
    vercel_environment = values.get("VERCEL_ENV", "")
    if vercel_environment and vercel_environment != environment:
        raise DeploymentError("DYNAMIS_DEPLOY_ENV does not match the Vercel environment")
    sha = _sha()
    release: dict[str, object] | None = None
    preview_receipt_path: Path | None = None
    if environment == "production":
        evidence = values.get("DYNAMIS_RELEASE_EVIDENCE", "").strip()
        if not evidence:
            raise DeploymentError("production seed requires completed preview release evidence")
        gate = Path(__file__).with_name("release_gate.py")
        subprocess.run([sys.executable, str(gate), evidence, "--git-sha", sha], check=True)
        release = json.loads(Path(evidence).read_text(encoding="utf-8"))

    seeds = load_public_seed()
    allowlisted = {item.dataset_id for item in seeds}
    artifact_selection: tuple[str, str] | None = None
    if environment == "production":
        assert release is not None
        preview_receipt_value = release.get("artifact_receipt")
        if not isinstance(preview_receipt_value, str) or not preview_receipt_value:
            raise DeploymentError("Preview release evidence is missing its artifact receipt")
        preview_receipt_path = Path(preview_receipt_value)
        if not preview_receipt_path.is_absolute():
            preview_receipt_path = (
                Path(values["DYNAMIS_RELEASE_EVIDENCE"]).resolve().parent / preview_receipt_path
            )
        preview_receipt = json.loads(preview_receipt_path.read_text(encoding="utf-8"))
        objects = preview_receipt.get("objects")
        if not isinstance(objects, list) or len(objects) != 1:
            raise DeploymentError("Preview release must select exactly one artifact")
        selected = objects[0]
        dataset_id = selected.get("dataset_id")
        checksum = selected.get("checksum_sha256")
        if not isinstance(dataset_id, str) or dataset_id not in allowlisted:
            raise DeploymentError("Preview artifact dataset is outside the production allowlist")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise DeploymentError("Preview artifact checksum is invalid")
        if artifact_dataset_id and artifact_dataset_id != dataset_id:
            raise DeploymentError("Production artifact dataset must match the Preview receipt")
        if artifact_checksum_sha256 and artifact_checksum_sha256 != checksum:
            raise DeploymentError("Production artifact checksum must match the Preview receipt")
        artifact_selection = (dataset_id, checksum)
    elif artifact_dataset_id or artifact_checksum_sha256:
        if (
            not artifact_dataset_id
            or artifact_dataset_id not in allowlisted
            or not artifact_checksum_sha256
            or not re.fullmatch(r"[0-9a-f]{64}", artifact_checksum_sha256)
        ):
            raise DeploymentError(
                "Preview artifact selection requires one allowlisted dataset id and "
                "lowercase SHA-256"
            )
        artifact_selection = (artifact_dataset_id, artifact_checksum_sha256)
    if apply and artifact_selection is None:
        raise DeploymentError(
            "Preview seed requires --artifact-dataset-id and --artifact-checksum-sha256"
        )
    if not apply:
        print(
            json.dumps(
                {
                    "environment": environment,
                    "git_sha": sha,
                    "datasets": [
                        {"dataset_id": item.dataset_id, "version": item.version, "keys": item.keys}
                        for item in seeds
                    ],
                    "restricted_sources_excluded": [
                        "sportsdataverse",
                        "tackle-workload",
                        "womens-soccer-positioning",
                        "spl-open-data",
                        "openbiomechanics",
                    ],
                    "artifact_selection": (
                        {
                            "dataset_id": artifact_selection[0],
                            "checksum_sha256": artifact_selection[1],
                        }
                        if artifact_selection
                        else None
                    ),
                },
                indent=2,
            )
        )
        return 0

    database_url = values.get(ENV_POSTGRES_URL, "").strip()
    migration_url = values.get(ENV_MIGRATION_POSTGRES_URL, "").strip()
    if not database_url:
        raise DeploymentError("POSTGRES_URL must target the isolated Neon deployment branch")
    if not migration_url:
        raise DeploymentError("DYNAMIS_MIGRATION_POSTGRES_URL must be set for schema verification")
    database_target = _database_target(database_url)
    if _database_target(migration_url) != database_target:
        raise DeploymentError("pooled and migration URLs must target the same Neon endpoint")
    if values.get("DYNAMIS_OBJECT_STORE_PROVIDER") != "vercel-blob":
        raise DeploymentError("DYNAMIS_OBJECT_STORE_PROVIDER must be vercel-blob")
    if release is not None:
        if release.get("database_target_sha256") == database_target:
            raise DeploymentError("Production and Preview must use isolated Neon endpoints")
        preview_receipt = release.get("artifact_receipt")
        if not isinstance(preview_receipt, str) or not preview_receipt:
            raise DeploymentError("Preview evidence must include its artifact receipt")
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, str(root / "infra/deploy/check_migrations.py")],
        cwd=root,
        check=True,
    )
    before = _database_source_ids()
    unexpected = sorted(before - allowlisted)
    if unexpected:
        raise DeploymentError(
            "target Neon branch contains unapproved sources: " + ", ".join(unexpected)
        )

    # Both SkillCorner adapters link session metadata to contest catalog entries.
    # Register those metadata-only entries before dense ingestion so the session
    # foreign keys are valid on a fresh deployment database.
    if "skillcorner-opendata" in allowlisted:
        from dynamis.adapters.skillcorner.catalog import register_skillcorner_corpus

        result = register_skillcorner_corpus(verify_upstream=False)
        if result.get("dataset_id") != "skillcorner-opendata":
            raise DeploymentError("SkillCorner metadata registration returned an unexpected source")
    if "skillcorner-basketball-opendata" in allowlisted:
        from dynamis.adapters.skillcorner_basketball.catalog import register_corpus

        result = register_corpus(verify_upstream=False)
        if result.get("dataset_id") != "skillcorner-basketball-opendata":
            raise DeploymentError(
                "SkillCorner Basketball metadata registration returned an unexpected source"
            )

    from dynamis.pipeline.cli import main as ingest

    for seed in seeds:
        argv = [seed.dataset_id, "--version", seed.version, "--json"]
        if seed.session_id:
            argv.extend(("--session", seed.session_id))
        for key in seed.keys:
            argv.extend(("--key", key))
        if ingest(argv) != 0:
            raise DeploymentError(f"ingestion failed for {seed.dataset_id}; stopping seed")

    from dynamis.demo.prepare import main as prepare_flagship

    if prepare_flagship([]) != 0:
        raise DeploymentError("accepted DFL/SkillCorner Gold preparation failed")
    subprocess.run(
        [sys.executable, str(root / "infra/deploy/check_migrations.py"), "--require-gold"],
        cwd=root,
        check=True,
    )
    upload_script = root / "infra/deploy/upload_artifacts.py"
    receipt_path = root / "output" / "deploy" / f"{environment}-artifacts-{sha}.json"
    assert artifact_selection is not None
    subprocess.run(
        [
            sys.executable,
            str(upload_script),
            "--apply",
            "--dataset-id",
            artifact_selection[0],
            "--checksum-sha256",
            artifact_selection[1],
            "--receipt",
            str(receipt_path),
        ],
        cwd=root,
        check=True,
    )
    from infra.deploy.verify_artifact_receipt import compare_receipts, verify

    failures = verify(receipt_path, environment, sha)
    if failures:
        raise DeploymentError("artifact reconciliation failed: " + "; ".join(failures))
    if release is not None:
        assert preview_receipt_path is not None
        failures = compare_receipts(preview_receipt_path, receipt_path, sha)
        if failures:
            raise DeploymentError("production seed differs from Preview: " + "; ".join(failures))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate only; no database or object writes"
    )
    parser.add_argument(
        "--apply", action="store_true", help="seed Neon and upload allowlisted artifacts"
    )
    parser.add_argument(
        "--artifact-dataset-id", help="dataset of the one approved Preview artifact"
    )
    parser.add_argument(
        "--artifact-checksum-sha256", help="SHA-256 of the one approved Preview artifact"
    )
    args = parser.parse_args(argv)
    if args.check == args.apply:
        parser.error("choose exactly one of --check or --apply")
    try:
        return run(args.apply, args.artifact_dataset_id, args.artifact_checksum_sha256)
    except (DeploymentError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"deployment seed blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
