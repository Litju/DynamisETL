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

from sqlalchemy.exc import SQLAlchemyError

from dynamis.acquisition.plan import PlanError, select_keys
from dynamis.adapters.gymaware_landmine.adapter import (
    adapter_algorithm_spec as gymaware_algorithm_spec,
)
from dynamis.adapters.gymaware_landmine.authorities import GYMAWARE_DATASET_ID
from dynamis.adapters.skillcorner.authorities import (
    SKILLCORNER_DATASET_ID,
)
from dynamis.adapters.skillcorner.authorities import (
    adapter_algorithm_spec as skillcorner_algorithm_spec,
)
from dynamis.adapters.spl.adapter import SplTrialSource
from dynamis.adapters.spl.authorities import (
    SPL_DATASET_ID,
)
from dynamis.adapters.spl.authorities import (
    adapter_algorithm_spec as spl_algorithm_spec,
)
from dynamis.adapters.sportec_idsse.adapter import adapter_algorithm_spec as idsse_algorithm_spec
from dynamis.adapters.white_cmj.adapter import (
    adapter_algorithm_spec as white_algorithm_spec,
)
from dynamis.adapters.white_cmj.authorities import WHITE_DATASET_ID, WHITE_NPZ_KEY
from dynamis.adapters.womens_soccer_positioning.adapter import (
    adapter_algorithm_spec as womens_algorithm_spec,
)
from dynamis.adapters.womens_soccer_positioning.authorities import WOMENS_DATASET_ID
from dynamis.config import ConfigurationError, settings
from dynamis.pipeline.ingest import (
    WORKBOOK_KEY_J01,
    IngestResult,
    ingest_dfl_match,
    ingest_gymaware_landmine,
    ingest_skillcorner_match,
    ingest_spl_trials,
    ingest_white_cmj,
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
SKILLCORNER_MATCH_TOKEN = re.compile(r"matches/(?P<match>\d+)/")
SPL_PARTICIPANT_TOKEN = re.compile(r"/(?P<participant>P\d+)/BB_FT_")
SUPPORTED_DATASETS = {
    "womens-soccer-positioning": "womens soccer positioning (GNSS)",
    "dfl-sportec-idsse": "DFL/Sportec IDSSE (tracking + events)",
    "white-cmj-acc-grf": "White CMJ accelerometer + vGRF (per-trial IMU + force)",
    "gymaware-landmine-vision": "GymAware landmine press + vision (source metrics)",
    "skillcorner-opendata": "SkillCorner Open Data (tracking + body pose)",
    "spl-open-data": "SPL Open Data (basketball free-throw pose)",
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
    parser.add_argument(
        "--discovery",
        action="store_true",
        help="Also write the structural discovery receipt (extra full source pass)",
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
    if dataset_id == WHITE_DATASET_ID:
        return "white-cmj-release"
    if dataset_id == GYMAWARE_DATASET_ID:
        return "gymaware-landmine-release"
    if dataset_id == SKILLCORNER_DATASET_ID:
        for key in keys:
            match = SKILLCORNER_MATCH_TOKEN.search(key)
            if match:
                return match.group("match")
        raise PlanError("cannot derive the SkillCorner match identity from the selected keys")
    if dataset_id == SPL_DATASET_ID:
        for key in keys:
            match = SPL_PARTICIPANT_TOKEN.search(key)
            if match:
                return match.group("participant")
        raise PlanError("cannot derive the SPL participant identity from the selected keys")
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


def _write_discovery(
    config, args: argparse.Namespace, paths: dict[str, Path], session_id: str
) -> None:
    """Write the structural discovery receipt for the selected source slice."""
    from dynamis.pipeline.ingest import write_discovery_receipts

    def first(token: str) -> Path | None:
        return next((path for key, path in paths.items() if token in key), None)

    if args.dataset_id == WOMENS_DATASET_ID:
        workbook = first(".xlsx")
        if workbook is None:
            raise PlanError("no workbook key selected for the Women's source")
        write_discovery_receipts(
            config,
            dataset_id=args.dataset_id,
            version=args.version,
            workbook_path=workbook,
            name=f"{session_id}-workbook",
        )
        return
    if args.dataset_id == WHITE_DATASET_ID:
        npz = next(
            (path for key, path in paths.items() if key == WHITE_NPZ_KEY),
            None,
        )
        if npz is None:
            raise PlanError("no accepted .npz key selected for the White CMJ source")
        write_discovery_receipts(
            config,
            dataset_id=args.dataset_id,
            version=args.version,
            npz_path=npz,
            name=f"{session_id}-npz",
        )
        return
    if args.dataset_id == GYMAWARE_DATASET_ID:
        archive = next((path for key, path in paths.items() if key.lower().endswith(".zip")), None)
        if archive is None:
            raise PlanError("no accepted .zip key selected for the GymAware source")
        write_discovery_receipts(
            config,
            dataset_id=args.dataset_id,
            version=args.version,
            archive_path=archive,
            name=f"{session_id}-zip",
        )
        return
    if args.dataset_id == SKILLCORNER_DATASET_ID:
        metadata_path = next(
            (path for key, path in paths.items() if key.endswith("_match.json")), None
        )
        tracking = next(
            (path for key, path in paths.items() if key.endswith("_tracking_extrapolated.jsonl")),
            None,
        )
        pose = next((path for key, path in paths.items() if key.endswith(".jsonl.zip")), None)
        if metadata_path is None or tracking is None or pose is None:
            raise PlanError(
                "SkillCorner discovery requires the match metadata, tracking and pose archive"
            )
        write_discovery_receipts(
            config,
            dataset_id=args.dataset_id,
            version=args.version,
            skillcorner_metadata_path=metadata_path,
            skillcorner_tracking_path=tracking,
            skillcorner_pose_path=pose,
            name=f"{session_id}-match",
        )
        return
    if args.dataset_id == SPL_DATASET_ID:
        spl_trials = tuple(
            SplTrialSource(key=key, path=path)
            for key, path in paths.items()
            if key.endswith(".json")
        )
        if not spl_trials:
            raise PlanError("no accepted SPL trial key selected")
        write_discovery_receipts(
            config,
            dataset_id=args.dataset_id,
            version=args.version,
            spl_trial_paths=spl_trials,
            name=f"{session_id}-pose",
        )
        return
    write_discovery_receipts(
        config,
        dataset_id=args.dataset_id,
        version=args.version,
        match_information_path=first("_matchinformation_"),
        events_path=first("_events_"),
        positions_path=first("_positions_"),
        name=f"{session_id}-xml",
    )


def _ingest(args: argparse.Namespace) -> tuple[IngestResult, str]:
    # Parameter validation first: a selection outside the registry must fail
    # regardless of whether this machine has scientific roots configured.
    keys = _selected_keys(args)
    config = settings()
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
    if args.discovery:
        _write_discovery(config, args, paths, session_id)

    if args.dataset_id == WOMENS_DATASET_ID:
        workbook = next((path for key, path in paths.items() if key.endswith(".xlsx")), None)
        if workbook is None:
            raise PlanError("no workbook key selected for the Women's source")
        result = ingest_womens_j01(
            config, workbook_path=workbook, version=args.version, session_id=session_id
        )
        return result, session_id
    if args.dataset_id == WHITE_DATASET_ID:
        npz = next((path for key, path in paths.items() if key == WHITE_NPZ_KEY), None)
        if npz is None:
            raise PlanError("no accepted .npz key selected for the White CMJ source")
        result = ingest_white_cmj(config, npz_path=npz, version=args.version)
        return result, session_id
    if args.dataset_id == GYMAWARE_DATASET_ID:
        archive = next((path for key, path in paths.items() if key.lower().endswith(".zip")), None)
        if archive is None:
            raise PlanError("no accepted .zip key selected for the GymAware source")
        result = ingest_gymaware_landmine(config, zip_path=archive, version=args.version)
        return result, session_id
    if args.dataset_id == SKILLCORNER_DATASET_ID:
        metadata_path = next(
            (path for key, path in paths.items() if key.endswith("_match.json")), None
        )
        tracking = next(
            (path for key, path in paths.items() if key.endswith("_tracking_extrapolated.jsonl")),
            None,
        )
        pose = next((path for key, path in paths.items() if key.endswith(".jsonl.zip")), None)
        missing_skillcorner = [
            name
            for name, value in (
                ("match metadata", metadata_path),
                ("tracking", tracking),
                ("pose archive", pose),
            )
            if value is None
        ]
        if missing_skillcorner:
            raise PlanError(
                f"SkillCorner ingestion requires the full match set; missing: {missing_skillcorner}"
            )
        assert metadata_path is not None and tracking is not None and pose is not None
        result = ingest_skillcorner_match(
            config,
            match_json_path=metadata_path,
            tracking_path=tracking,
            pose_zip_path=pose,
            version=args.version,
            batch_size=args.batch_size or 16384,
        )
        return result, session_id
    if args.dataset_id == SPL_DATASET_ID:
        spl_trials = tuple(
            SplTrialSource(key=key, path=path)
            for key, path in paths.items()
            if key.endswith(".json")
        )
        if not spl_trials:
            raise PlanError("no accepted SPL trial key selected")
        result = ingest_spl_trials(
            config,
            trials=spl_trials,
            version=args.version,
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
    suffix = "res97"
    if args.dataset_id in {WHITE_DATASET_ID, GYMAWARE_DATASET_ID}:
        suffix = "res98"
    elif args.dataset_id in {SKILLCORNER_DATASET_ID, SPL_DATASET_ID}:
        suffix = "res99"
    return persist_ingest(
        config,
        dataset_id=args.dataset_id,
        version=args.version,
        domain=result.provider_domain,
        result=result,
        algorithm=_adapter_algorithm(args.dataset_id),
        run_id=f"run-{session_id.lower()}-{suffix}",
        code_git_sha=code_git_sha,
    ).to_dict()


def _adapter_algorithm(dataset_id: str):
    if dataset_id == WOMENS_DATASET_ID:
        return womens_algorithm_spec()
    if dataset_id == WHITE_DATASET_ID:
        return white_algorithm_spec()
    if dataset_id == GYMAWARE_DATASET_ID:
        return gymaware_algorithm_spec()
    if dataset_id == SKILLCORNER_DATASET_ID:
        return skillcorner_algorithm_spec()
    if dataset_id == SPL_DATASET_ID:
        return spl_algorithm_spec()
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
        except (ConfigurationError, RuntimeError, SQLAlchemyError) as exc:
            # Persistence is a control-plane concern; a database outage must not
            # lose the ingestion summary that has already been written to disk.
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
