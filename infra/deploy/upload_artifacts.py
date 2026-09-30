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

import sqlalchemy as sa
from sqlalchemy import select

from dynamis.config import Settings, settings
from dynamis.deployment import (
    DeploymentError,
    load_public_demo_resources,
    load_public_seed,
    public_rights_error,
    rights_allowlist_sha256,
)
from dynamis.deployment_manifest import load_manifest, manifest_key, validate_manifest
from dynamis.registry import validate_registry
from dynamis.storage.atomic import atomic_write_text, sha256_file
from dynamis.storage.control_plane import control_plane_engine
from dynamis.storage.object_store import (
    ObjectStoreError,
    VercelPrivateBlobStore,
    immutable_object_key,
    object_store,
)
from dynamis.storage.tables import DatasetSource, LicensePolicy, SampleArtifact


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
    explicit = os.environ.get("DYNAMIS_CODE_GIT_SHA", "").strip()
    vercel = os.environ.get("VERCEL_GIT_COMMIT_SHA", "").strip()
    if explicit and vercel and explicit != vercel:
        raise DeploymentError("DYNAMIS_CODE_GIT_SHA does not match VERCEL_GIT_COMMIT_SHA")
    value = explicit or vercel
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
    demo_resources,
) -> list[tuple[str, Path, str, int, tuple[str, ...], tuple[str, ...]]]:
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

            for resource in demo_resources:
                dataset_id = resource.dataset_id
                session_id = resource.session_id
                entry_ids = (
                    connection.execute(
                        sa.text(
                            """SELECT DISTINCT source_catalog_entry_id
                           FROM session_sport_context
                           WHERE dataset_id = :dataset_id AND session_id = :session_id
                             AND source_catalog_entry_id IS NOT NULL"""
                        ),
                        {"dataset_id": dataset_id, "session_id": session_id},
                    )
                    .scalars()
                    .all()
                )
                sample_rows = connection.execute(
                    select(
                        SampleArtifact.artifact_id,
                        SampleArtifact.dataset_id,
                        SampleArtifact.relative_path,
                        SampleArtifact.checksum_sha256,
                        SampleArtifact.byte_size,
                    ).where(
                        SampleArtifact.dataset_id == dataset_id,
                        SampleArtifact.session_id == session_id,
                        SampleArtifact.format == "parquet",
                    )
                ).all()
                if not sample_rows:
                    raise DeploymentError(
                        f"{dataset_id}/{session_id}: curated World has no dense Parquet artifacts"
                    )
                processing_rows = connection.execute(
                    sa.text(
                        """SELECT artifact_id, dataset_id, relative_path,
                                  checksum_sha256, byte_size
                           FROM processing_artifact
                           WHERE dataset_id = :dataset_id
                             AND (artifact_metadata ->> 'session_id' = :session_id
                               OR artifact_metadata ->> 'source_catalog_entry_id'
                                  = ANY(CAST(:entry_ids AS text[])))
                           ORDER BY artifact_id"""
                    ),
                    {
                        "dataset_id": dataset_id,
                        "session_id": session_id,
                        "entry_ids": list(entry_ids),
                    },
                ).all()
                for kind, rows in (("sample", sample_rows), ("processing", processing_rows)):
                    for (
                        artifact_id,
                        artifact_dataset_id,
                        relative_path,
                        checksum,
                        byte_size,
                    ) in rows:
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

    uploads = [
        (
            item[0],
            item[1],
            item[2],
            item[3],
            tuple(sorted(item[4])),
            tuple(sorted(item[5])),
        )
        for item in found.values()
    ]
    return sorted(uploads, key=lambda row: (row[0], row[2]))


def upload(
    environment: str,
    receipt_path: Path | None = None,
) -> dict[str, object]:
    if environment not in {"preview", "production"}:
        raise DeploymentError("DYNAMIS_DEPLOY_ENV must be preview or production")
    git_sha = _sha()
    expected_preview_receipt: Path | None = None
    if environment == "production":
        evidence = os.environ.get("DYNAMIS_RELEASE_EVIDENCE", "").strip()
        if not evidence:
            raise DeploymentError("production upload requires completed preview release evidence")
        root = Path(__file__).resolve().parents[2]
        subprocess.run(
            [sys.executable, "-m", "infra.deploy.release_gate", evidence, "--git-sha", git_sha],
            cwd=root,
            check=True,
        )
        release = json.loads(Path(evidence).read_text(encoding="utf-8"))
        receipt_value = release.get("artifact_receipt")
        if not isinstance(receipt_value, str) or not receipt_value:
            raise DeploymentError("Preview release evidence is missing its artifact receipt")
        expected_preview_receipt = Path(receipt_value)
        if not expected_preview_receipt.is_absolute():
            expected_preview_receipt = Path(evidence).resolve().parent / expected_preview_receipt

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

    demo_resources = load_public_demo_resources()
    uploads = _artifacts(resolved, ids, demo_resources)
    receipts = [
        UploadReceipt(
            environment=environment,
            git_sha=git_sha,
            object_key=immutable_object_key(checksum),
            dataset_id=artifact_dataset_id,
            checksum_sha256=checksum,
            size_bytes=size_bytes,
            source_kinds=source_kinds,
            artifact_ids=artifact_ids,
        )
        for artifact_dataset_id, _path, checksum, size_bytes, artifact_ids, source_kinds in uploads
    ]
    report = {
        "schema_version": 1,
        "environment": environment,
        "git_sha": git_sha,
        "manifest_key": manifest_key(environment, git_sha),
        "rights_allowlist_sha256": rights_allowlist_sha256(),
        "allowlisted_datasets": sorted(ids),
        "demo_resources": [
            {
                "dataset_id": item.dataset_id,
                "session_id": item.session_id,
                "worlds": list(item.worlds),
            }
            for item in demo_resources
        ],
        "object_count": len(receipts),
        "byte_count": sum(item.size_bytes for item in receipts),
        "objects": [asdict(item) for item in receipts],
    }
    failures = validate_manifest(report, environment, git_sha)
    if failures:
        raise DeploymentError("curated artifact plan failed validation: " + "; ".join(failures))

    if expected_preview_receipt is not None:
        try:
            preview_report = json.loads(expected_preview_receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeploymentError("Preview artifact receipt is missing or invalid") from exc
        failures = validate_manifest(preview_report, "preview", git_sha)
        if failures:
            raise DeploymentError("Preview receipt failed validation: " + "; ".join(failures))
        if _object_identity(preview_report) != _object_identity(report):
            raise DeploymentError("Production object plan differs from the Preview receipt")

    for artifact_dataset_id, path, checksum, size_bytes, _artifact_ids, _source_kinds in uploads:
        key = immutable_object_key(checksum)
        uploaded = store.put_file(path, key=key, checksum_sha256=checksum)
        if uploaded.sha256 != checksum or uploaded.size_bytes != size_bytes:
            raise ObjectStoreError(
                f"private Blob reconciliation failed for {artifact_dataset_id}/{key}"
            )

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
    manifest_digest = sha256_file(receipt_path)
    manifest_metadata = store.put_file(
        receipt_path,
        key=report["manifest_key"],
        checksum_sha256=manifest_digest,
    )
    if (
        manifest_metadata.sha256 != manifest_digest
        or manifest_metadata.size_bytes != receipt_path.stat().st_size
    ):
        raise ObjectStoreError("private Blob manifest reconciliation failed")
    if load_manifest(store, environment, git_sha) != frozenset(
        artifact_id for receipt in receipts for artifact_id in receipt.artifact_ids
    ):
        raise ObjectStoreError("deployed Private Blob manifest does not reconcile")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "objects"}, sort_keys=True
        )
    )
    print(f"receipt: {receipt_path}")
    return report


def _object_identity(receipt: dict[str, object]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        sorted(
            (
                item["dataset_id"],
                item["checksum_sha256"],
                item["object_key"],
                item["size_bytes"],
                tuple(sorted(item["source_kinds"])),
                tuple(sorted(item["artifact_ids"])),
            )
            for item in receipt["objects"]
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate rights and configuration only"
    )
    parser.add_argument("--apply", action="store_true", help="upload and reconcile private objects")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    if args.check == args.apply:
        parser.error("choose exactly one of --check or --apply")
    try:
        seeds = load_public_seed()
        if args.check:
            demo_resources = [
                {
                    "dataset_id": item.dataset_id,
                    "session_id": item.session_id,
                    "worlds": list(item.worlds),
                }
                for item in load_public_demo_resources()
            ]
            print(
                json.dumps(
                    {
                        "allowlisted_datasets": [seed.dataset_id for seed in seeds],
                        "demo_resources": demo_resources,
                    },
                    sort_keys=True,
                )
            )
            return 0
        environment = os.environ.get("DYNAMIS_DEPLOY_ENV", "")
        upload(environment, args.receipt)
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
