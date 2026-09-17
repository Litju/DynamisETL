"""``dynamis-ingest``: Bronze -> canonical Silver ingestion for RES-97 sources.

The CLI is the reproducible local surface: it resolves the accepted files from
immutable Bronze (never from the network), verifies the Bronze manifest, runs the
provider adapter, writes validated Silver Parquet plus reconciliation receipts,
and optionally persists the control-plane metadata to PostgreSQL.

    dynamis-ingest womens-soccer-positioning --version 1.0 --key J01.xlsx

    dynamis-ingest dfl-sportec-idsse \\
        --version a715a38dfbaf5f58e431727c2b78d174101a703c --match J03WPY

No source data is committed; everything lands under ``DYNAMIS_DATASET_ROOT``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from dynamis.acquisition.plan import PlanError, select_keys
from dynamis.adapters.sportec_idsse.adapter import adapter_algorithm_spec as idsse_algorithm_spec
from dynamis.adapters.womens_soccer_positioning.adapter import (
    adapter_algorithm_spec as womens_algorithm_spec,
)
from dynamis.adapters.womens_soccer_positioning.authorities import WOMENS_DATASET_ID
from dynamis.config import ConfigurationError, settings
from dynamis.pipeline.ingest import (
    WORKBOOK_KEY_J01,
    IngestResult,
    ingest_dfl_match,
    ingest_womens_j01,
)
from dynamis.registry import source_by_id, validate_registry
from dynamis.storage.manifest import (
    read_bronze_manifest,
    verify_manifest,
)
from dynamis.storage.paths import bronze_native_path, tmp_run_dir

EXIT_OK = 0
EXIT_FAILURE = 2

MATCH_TOKEN = re.compile(r"DFL-MAT-([A-Z0-9]+)")
SUPPORTED_DATASETS = {
    "womens-soccer-positioning": "womens soccer positioning (GNSS)",
    "dfl-sportec-idsse": "DFL/Sportec IDSSE (tracking + events)",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dynamis-ingest",
        description=(
            "Ingest accepted Bronze files into validated canonical Silver Parquet. "
            "Requires an explicit file selection and a verified Bronze manifest."
        ),
    )
    parser.add_argument("dataset_id", choices=sorted(SUPPORTED_DATASETS))
    parser.add_argument("--version", required=True, help="Pinned registry version/revision")
    parser.add_argument(
        "--key", action="append", default=[], help="Exact Bronze file key (repeatable)"
    )
    parser.add_argument(
        "--match", action="append", default=[], help="Substring selection (repeatable)"
    )
    parser.add_argument(
        "--all", action="store_true", dest="all_files", help="Select every declared file"
    )
    parser.add_argument("--session", default=None, help="Session identity override")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Adapter batch size (rows) for the DFL positions stream",
    )
    parser.add_argument(
        "--spill-dir",
        type=Path,
        default=None,
        help="Temporary spill directory (defaults to <dataset_root>/tmp/<run>)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Skip PostgreSQL control-plane persistence",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _selected_keys(args: argparse.Namespace) -> tuple[str, ...]:
    registry = validate_registry()
    source = source_by_id(registry, args.dataset_id)
    version = source.version(args.version)
    return select_keys(version, keys=args.key, match=args.match, all_files=args.all_files)


def _default_session(dataset_id: str, keys: Sequence[str]) -> str:
    if dataset_id == WOMENS_DATASET_ID:
        return Path(WORKBOOK_KEY_J01).stem
    for key in keys:
        match = MATCH_TOKEN.search(key)
        if match:
            return f"DFL-MAT-{match.group(1)}"
    raise PlanError("cannot derive the DFL match identity from the selected keys")


def _resolve_bronze_paths(
    settings, keys: Sequence[str], *, dataset_id: str, version: str
) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key in keys:
        path = bronze_native_path(settings, dataset_id=dataset_id, version=version, key=key)
        if not path.is_file():
            raise FileNotFoundError(
                f"Bronze file missing for {dataset_id}/{version}: {key}; run dynamis-fetch first"
            )
        paths[key] = path
    return paths


def _ingest(args: argparse.Namespace) -> tuple[IngestResult, str]:
    config = settings()
    keys = _selected_keys(args)
    manifest = read_bronze_manifest(config, dataset_id=args.dataset_id, version=args.version)
    verification = verify_manifest(config, manifest)
    if not verification.ok:
        raise RuntimeError(
            "Bronze manifest verification failed: "
            f"missing={list(verification.missing)} mismatched={list(verification.mismatched)} "
            f"size_mismatched={list(verification.size_mismatched)}"
        )
    paths = _resolve_bronze_paths(config, keys, dataset_id=args.dataset_id, version=args.version)
    session_id = args.session or _default_session(args.dataset_id, keys)

    if args.dataset_id == WOMENS_DATASET_ID:
        workbook = next((path for key, path in paths.items() if key.endswith(".xlsx")), None)
        if workbook is None:
            raise PlanError("no workbook key selected for the Women's source")
        result = ingest_womens_j01(
            config, workbook_path=workbook, version=args.version, session_id=session_id
        )
        return result, session_id

    positions = next((path for key, path in paths.items() if "_positions_" in key), None)
    events = next((path for key, path in paths.items() if "_events_" in key), None)
    information = next((path for key, path in paths.items() if "_matchinformation_" in key), None)
    missing = [
        name
        for name, value in (
            ("matchinformation", information),
            ("events", events),
            ("positions", positions),
        )
        if value is None
    ]
    if missing:
        raise PlanError(f"DFL ingestion requires the full match set; missing: {missing}")
    assert positions is not None and events is not None and information is not None
    spill_dir = args.spill_dir or tmp_run_dir(config, f"res97-{session_id}-spill")
    result = ingest_dfl_match(
        config,
        match_information_path=information,
        events_path=events,
        positions_path=positions,
        version=args.version,
        session_id=session_id,
        spill_dir=spill_dir,
        batch_size=args.batch_size,
    )
    return result, session_id


def _persist(args: argparse.Namespace, result: IngestResult, session_id: str) -> dict[str, Any]:
    from dynamis.pipeline.persist import persist_ingest

    config = settings()
    code_git_sha = _git_sha()
    return persist_ingest(
        config,
        dataset_id=args.dataset_id,
        version=args.version,
        domain=result.provider_domain,
        result=result,
        algorithm=_adapter_algorithm(args.dataset_id),
        run_id=f"run-{session_id.lower()}-res97",
        code_git_sha=code_git_sha,
    ).to_dict()


def _adapter_algorithm(dataset_id: str):
    if dataset_id == WOMENS_DATASET_ID:
        return womens_algorithm_spec()
    return idsse_algorithm_spec()


def _git_sha() -> str | None:
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result, session_id = _ingest(args)
    except (
        ConfigurationError,
        FileNotFoundError,
        PlanError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"dynamis-ingest: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    payload: dict[str, Any] = {
        "ingest": result.to_dict(),
        "persist": None,
    }
    if not args.no_persist:
        try:
            payload["persist"] = _persist(args, result, session_id)
        except (ConfigurationError, RuntimeError) as exc:
            payload["persist"] = {"skipped": str(exc)}
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        reconciliation = result.reconciliation
        print(
            f"ingested {result.dataset_id}/{result.version} session={result.session_id}: "
            f"source={reconciliation.source_rows} canonical={reconciliation.canonical_rows} "
            f"quarantined={reconciliation.quarantined_rows} "
            f"balanced={reconciliation.all_balanced}"
        )
        for stream in result.streams:
            print(
                f"  {stream.modality}/{stream.stream_id}: rows={stream.row_count} "
                f"bytes={stream.byte_size} sha256={stream.checksum_sha256[:16]}..."
            )
        print(f"  reconciliation receipt: {result.receipt_path}")
        persist = payload["persist"]
        if isinstance(persist, dict) and persist.get("run_id"):
            print(f"  postgres: run_id={persist['run_id']} rows={persist['rows_written']}")
        elif isinstance(persist, dict):
            print(f"  postgres: skipped ({persist.get('skipped')})")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via console script
    raise SystemExit(main())
