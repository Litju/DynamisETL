"""Upload and reconcile rights-approved Parquet artifacts in Vercel Private Blob."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from dynamis.config import Settings, settings
from dynamis.deployment import DeploymentError, load_public_seed, public_rights_error
from dynamis.registry import validate_registry
from dynamis.storage.atomic import atomic_write_text, sha256_file
from dynamis.storage.control_plane import control_plane_engine
from dynamis.storage.object_store import (
    ObjectStoreError,
    VercelPrivateBlobStore,
    immutable_object_key,
    object_store,
)
from dynamis.storage.tables import DatasetSource, LicensePolicy, ProcessingArtifact, SampleArtifact


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    environment: str
    git_sha: str
    object_key: str
    dataset_id: str
    checksum_sha256: str
    size_bytes: int
    source_kinds: tuple[str, ...]
    artifact_ids: tuple[str, ...]


def _sha() -> str:
    value = os.environ.get("DYNAMIS_CODE_GIT_SHA", "").strip()
    if not value:
        import subprocess

        value = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise DeploymentError("DYNAMIS_CODE_GIT_SHA must be a 40-character lowercase Git SHA")
    return value


def _assert_registry_rights(dataset_id: str, policy: object, expected: object) -> None:
    if policy is None:
        raise DeploymentError(f"{dataset_id}: database license policy is missing")
    fields = (
        "identifier",
        "status",
        "attribution_required",
        "noncommercial_only",
        "share_alike",
        "redistribution",
        "local_only",
        "restrictions",
    )
    differences = []
    for field in fields:
        actual_value = getattr(policy, field)
        expected_value = getattr(expected, field)
        if field in {"status", "redistribution"}:
            actual_value = getattr(actual_value, "value", actual_value)
            expected_value = getattr(expected_value, "value", expected_value)
        elif field == "restrictions":
            actual_value = tuple(actual_value or ())
            expected_value = tuple(expected_value or ())
        if actual_value != expected_value:
            differences.append(field)
    if differences:
        raise DeploymentError(
            f"{dataset_id}: database rights differ from the registry ({', '.join(differences)})"
        )
    if blocked := public_rights_error(policy):
        raise DeploymentError(f"{dataset_id}: {blocked}; refusing object upload")


def _artifacts(
    resolved: Settings,
    ids: set[str],
    *,
    dataset_id: str,
    checksum_sha256: str,
) -> list[tuple[str, Path, str, int, tuple[str, ...], tuple[str, ...]]]:
    if dataset_id not in ids:
        raise DeploymentError(f"{dataset_id}: dataset is outside the production rights allowlist")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum_sha256):
        raise DeploymentError("artifact selection requires a lowercase SHA-256 checksum")

    engine = control_plane_engine(resolved)
    found: dict[tuple[str, str], tuple[str, Path, str, int, set[str], set[str]]] = {}
    try:
        with engine.connect() as connection:
            registry = validate_registry()
            source_rows = (
                connection.execute(
                    select(
                        DatasetSource.dataset_id,
                        LicensePolicy.policy_id,
                        LicensePolicy.identifier,
                        LicensePolicy.status,
                        LicensePolicy.attribution_required,
                        LicensePolicy.noncommercial_only,
                        LicensePolicy.share_alike,
                        LicensePolicy.redistribution,
                        LicensePolicy.local_only,
                        LicensePolicy.restrictions,
                    ).outerjoin(
                        LicensePolicy, DatasetSource.license_policy_id == LicensePolicy.policy_id
                    )
                )
                .mappings()
                .all()
            )
            registered = {row["dataset_id"] for row in source_rows}
            unexpected = sorted(registered - ids)
            if unexpected:
                raise DeploymentError(
                    "preview database contains source ids outside the public allowlist: "
                    + ", ".join(unexpected)
                )
            missing_sources = sorted(ids - registered)
            if missing_sources:
                raise DeploymentError(
                    "preview database is missing allowlisted sources: " + ", ".join(missing_sources)
                )
            for row in source_rows:
                source_dataset_id = row["dataset_id"]
                if source_dataset_id in ids:
                    policy = (
                        None
                        if row["policy_id"] is None
                        else SimpleNamespace(
                            identifier=row["identifier"],
                            status=row["status"],
                            attribution_required=row["attribution_required"],
                            noncommercial_only=row["noncommercial_only"],
                            share_alike=row["share_alike"],
                            redistribution=row["redistribution"],
                            local_only=row["local_only"],
                            restrictions=row["restrictions"],
                        )
                    )
                    _assert_registry_rights(
                        source_dataset_id, policy, registry.source(source_dataset_id).license
                    )

            sample_rows = connection.execute(
                select(
                    SampleArtifact.artifact_id,
                    SampleArtifact.dataset_id,
                    SampleArtifact.relative_path,
                    SampleArtifact.checksum_sha256,
                    SampleArtifact.byte_size,
                ).where(
                    SampleArtifact.dataset_id.in_(ids),
                    SampleArtifact.dataset_id == dataset_id,
                    SampleArtifact.checksum_sha256 == checksum_sha256,
                    SampleArtifact.format == "parquet",
                )
            )
            processing_rows = connection.execute(
                select(
                    ProcessingArtifact.artifact_id,
                    ProcessingArtifact.dataset_id,
                    ProcessingArtifact.relative_path,
                    ProcessingArtifact.checksum_sha256,
                    ProcessingArtifact.byte_size,
                ).where(
                    ProcessingArtifact.dataset_id.in_(ids),
                    ProcessingArtifact.dataset_id == dataset_id,
                    ProcessingArtifact.checksum_sha256 == checksum_sha256,
                )
            )
            for kind, rows in (("sample", sample_rows), ("processing", processing_rows)):
                for artifact_id, artifact_dataset_id, relative_path, checksum, byte_size in rows:
                    if not relative_path.lower().endswith(".parquet"):
                        continue
                    if byte_size is None or byte_size <= 0:
                        raise DeploymentError(
                            f"{artifact_dataset_id}/{relative_path}: byte size is missing"
                        )
                    checksum = checksum.lower()
                    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                        raise DeploymentError(
                            f"{artifact_dataset_id}/{relative_path}: invalid SHA-256"
                        )
                    relative = Path(relative_path)
                    root = resolved.dataset_root.resolve()
                    source_path = (root / relative).resolve()
                    if relative.is_absolute() or not source_path.is_relative_to(root):
                        raise DeploymentError(
                            f"{artifact_dataset_id}/{relative_path}: unsafe artifact path"
                        )
                    if not source_path.is_file():
                        raise DeploymentError(
                            f"{artifact_dataset_id}/{relative_path}: artifact file is missing"
                        )
                    if source_path.stat().st_size != byte_size:
                        raise DeploymentError(
                            f"{artifact_dataset_id}/{relative_path}: byte size mismatch"
                        )
                    if sha256_file(source_path) != checksum:
                        raise DeploymentError(
                            f"{artifact_dataset_id}/{relative_path}: source checksum mismatch"
                        )
                    identity = (artifact_dataset_id, checksum)
                    prior = found.get(identity)
                    if prior is not None and prior[3] != byte_size:
                        raise DeploymentError(
                            f"{artifact_dataset_id}: checksum has conflicting byte sizes"
                        )
                    if prior is None:
                        found[identity] = (
                            artifact_dataset_id,
                            source_path,
                            checksum,
                            byte_size,
                            {artifact_id},
                            {kind},
                        )
                    else:
                        prior[4].add(artifact_id)
                        prior[5].add(kind)
    finally:
        engine.dispose()

    selected = [
        item for item in found.values() if item[0] == dataset_id and item[2] == checksum_sha256
    ]
    if len(selected) != 1:
        raise DeploymentError(
            f"{dataset_id}/{checksum_sha256}: expected exactly one registered, checksum-matched "
            "Parquet object"
        )
    uploads = [
        (
            item[0],
            item[1],
            item[2],
            item[3],
            tuple(sorted(item[4])),
            tuple(sorted(item[5])),
        )
        for item in selected
    ]
    return sorted(uploads, key=lambda row: (row[0], row[2]))


def upload(
    environment: str,
    dataset_id: str,
    checksum_sha256: str,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    if environment not in {"preview", "production"}:
        raise DeploymentError("DYNAMIS_DEPLOY_ENV must be preview or production")
    git_sha = _sha()
    if environment == "production":
        evidence = os.environ.get("DYNAMIS_RELEASE_EVIDENCE", "").strip()
        if not evidence:
            raise DeploymentError("production upload requires completed preview release evidence")
        gate = Path(__file__).with_name("release_gate.py")
        subprocess.run([sys.executable, str(gate), evidence, "--git-sha", git_sha], check=True)

    seeds = load_public_seed()
    ids = {seed.dataset_id for seed in seeds}
    resolved = settings()
    if resolved.object_store_provider != "vercel-blob":
        raise DeploymentError(
            "DYNAMIS_OBJECT_STORE_PROVIDER must be vercel-blob for deployment uploads"
        )
    store = object_store(resolved)
    if not isinstance(store, VercelPrivateBlobStore):
        raise DeploymentError("deployment uploads require Vercel Private Blob")

    receipts: list[UploadReceipt] = []
    for artifact_dataset_id, path, checksum, size_bytes, artifact_ids, source_kinds in _artifacts(
        resolved,
        ids,
        dataset_id=dataset_id,
        checksum_sha256=checksum_sha256,
    ):
        key = immutable_object_key(checksum)
        uploaded = store.put_file(path, key=key, checksum_sha256=checksum)
        if uploaded.sha256 != checksum or uploaded.size_bytes != size_bytes:
            raise ObjectStoreError(
                f"private Blob reconciliation failed for {artifact_dataset_id}/{key}"
            )
        receipts.append(
            UploadReceipt(
                environment=environment,
                git_sha=git_sha,
                object_key=key,
                dataset_id=artifact_dataset_id,
                checksum_sha256=checksum,
                size_bytes=size_bytes,
                source_kinds=source_kinds,
                artifact_ids=artifact_ids,
            )
        )

    report = {
        "environment": environment,
        "git_sha": git_sha,
        "allowlisted_datasets": sorted(ids),
        "object_count": len(receipts),
        "byte_count": sum(item.size_bytes for item in receipts),
        "objects": [asdict(item) for item in receipts],
    }
    if receipt_path is None:
        configured = os.environ.get("DYNAMIS_ARTIFACT_RECEIPT", "").strip()
        receipt_path = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[2]
            / "output"
            / "deploy"
            / f"{environment}-artifacts-{git_sha}.json"
        )
    atomic_write_text(receipt_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "objects"}, sort_keys=True
        )
    )
    print(f"receipt: {receipt_path}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate rights and configuration only"
    )
    parser.add_argument("--apply", action="store_true", help="upload and reconcile private objects")
    parser.add_argument("--dataset-id", help="one production-allowlisted artifact dataset")
    parser.add_argument("--checksum-sha256", help="exact SHA-256 of the one Parquet artifact")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    if args.check == args.apply:
        parser.error("choose exactly one of --check or --apply")
    try:
        seeds = load_public_seed()
        if args.check:
            print(
                json.dumps(
                    {"allowlisted_datasets": [seed.dataset_id for seed in seeds]}, sort_keys=True
                )
            )
            return 0
        environment = os.environ.get("DYNAMIS_DEPLOY_ENV", "")
        if not args.dataset_id or not args.checksum_sha256:
            raise DeploymentError("--apply requires one --dataset-id and --checksum-sha256")
        upload(environment, args.dataset_id, args.checksum_sha256, args.receipt)
    except (
        DeploymentError,
        ObjectStoreError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"deployment object seed blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
