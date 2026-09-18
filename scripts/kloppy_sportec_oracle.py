"""Independent real-data Sportec event-coordinate oracle (RES-103 closure).

Verification & validation only. The accepted local J03WPY Bronze files are read
from ``DYNAMIS_DATASET_ROOT`` (never the network, never the repository), every
coordinate-bearing canonical event is replayed through DynamisETL's declared
corner->centre frame transform, and the *same raw source coordinates* are passed
through the pinned executable Kloppy reader
(``sportec.load_event(..., coordinates="sportec:tracking")``). The comparison
therefore exercises two independently implemented transformations of identical
source points.

Kloppy's prose is internally inconsistent (the ``SportecEventDataCoordinateSystem``
docstring says the y-axis runs top-to-bottom) while its executable properties
return ``BOTTOM_TO_TOP`` for both event and tracking systems. This script trusts
execution, never prose.

Output: an external JSON receipt containing counts and coordinate deltas only
(no source rows) under
``cache/receipts/dfl-sportec-idsse/coordinate-oracle/<match>-events.json``.
Exits non-zero on Kloppy version drift or a mismatch beyond the tolerance.

Usage (Kloppy is pinned in the dev dependency group)::

    uv run python scripts/kloppy_sportec_oracle.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dynamis.adapters.sportec_idsse.adapter import (  # noqa: E402 - path bootstrap
    IdsseMatchAdapter,
)
from dynamis.config import settings  # noqa: E402 - path bootstrap
from dynamis.storage.atomic import atomic_write_text  # noqa: E402 - path bootstrap
from dynamis.storage.manifest import (  # noqa: E402 - path bootstrap
    BronzeManifest,
    read_bronze_manifest,
    verify_manifest,
)
from dynamis.storage.paths import (  # noqa: E402 - path bootstrap
    bronze_native_path,
    receipt_path,
    tmp_run_dir,
)

DATASET_ID = "dfl-sportec-idsse"
DEFAULT_VERSION = "a715a38dfbaf5f58e431727c2b78d174101a703c"
DEFAULT_MATCH = "J03WPY"
DEFAULT_TOLERANCE_M = 1e-9
PINNED_KLOPPY_VERSION = "3.19.0"


def _key_for(manifest: BronzeManifest, token: str) -> str:
    key = next((item.key for item in manifest.files if token in item.key), None)
    if key is None:
        raise SystemExit(f"no Bronze file matches {token!r} in {DATASET_ID}")
    return key


def _dynamisetl_event_points(adapter: IdsseMatchAdapter) -> dict[str, tuple[float, float]]:
    """Canonical event coordinates as DynamisETL publishes them."""
    points: dict[str, tuple[float, float]] = {}
    for batch in adapter.event_stream().batches:
        for row in batch.to_pylist():
            x_m, y_m = row["x_m"], row["y_m"]
            if x_m is not None and y_m is not None:
                points[str(row["event_id"])] = (float(x_m), float(y_m))
    return points


def _kloppy_event_points(
    events_path: Path, information_path: Path
) -> dict[str, tuple[float, float]]:
    """Coordinates produced by the pinned executable Kloppy Sportec reader."""
    from kloppy import sportec

    dataset = sportec.load_event(
        str(events_path),
        str(information_path),
        coordinates="sportec:tracking",
    )
    points: dict[str, tuple[float, float]] = {}
    for event in dataset.events:
        coordinates = event.coordinates
        if coordinates is not None:
            points[str(event.event_id)] = (float(coordinates.x), float(coordinates.y))
    return points


def _count_deleted_events_with_coordinates(events_path: Path) -> int:
    """Provider ``Delete`` retractions that carry coordinates (excluded canonically)."""
    import lxml.etree as etree

    count = 0
    for _event, elem in etree.iterparse(str(events_path), events=("end",), tag=("Event",)):
        if (
            len(elem)
            and isinstance(elem[0].tag, str)
            and elem[0].tag == "Delete"
            and elem.get("X-Position") is not None
            and elem.get("Y-Position") is not None
        ):
            count += 1
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
    return count


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kloppy-sportec-oracle",
        description=(
            "Compare DynamisETL's declared Sportec event transform with the pinned "
            "executable Kloppy Sportec transformation on immutable local Bronze."
        ),
    )
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--match", default=DEFAULT_MATCH)
    parser.add_argument(
        "--tolerance-m",
        type=float,
        default=DEFAULT_TOLERANCE_M,
        help="Maximum per-component coordinate disagreement (metres).",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        import kloppy
    except ImportError:
        print(
            "kloppy is required for the oracle (pinned in the dev dependency group)",
            file=sys.stderr,
        )
        return 2
    if kloppy.__version__ != PINNED_KLOPPY_VERSION:
        print(
            f"kloppy version drift: installed {kloppy.__version__}, "
            f"pinned {PINNED_KLOPPY_VERSION}; re-run the oracle deliberately after review",
            file=sys.stderr,
        )
        return 2

    resolved = settings()
    manifest = read_bronze_manifest(resolved, dataset_id=DATASET_ID, version=args.version)
    verification = verify_manifest(resolved, manifest)
    if not verification.ok:
        print(
            f"Bronze manifest verification failed: missing={list(verification.missing)} "
            f"mismatched={list(verification.mismatched)} "
            f"size_mismatched={list(verification.size_mismatched)}",
            file=sys.stderr,
        )
        return 2

    events_key = _key_for(manifest, "_events_")
    information_key = _key_for(manifest, "_matchinformation_")
    events_path = bronze_native_path(
        resolved, dataset_id=DATASET_ID, version=args.version, key=events_key
    )
    information_path = bronze_native_path(
        resolved, dataset_id=DATASET_ID, version=args.version, key=information_key
    )

    adapter = IdsseMatchAdapter(
        match_information_path=information_path,
        events_path=events_path,
        positions_path=information_path,  # never parsed by the event oracle
        version=args.version,
        spill_dir=tmp_run_dir(resolved, "res103-sportec-oracle"),
    )
    ours = _dynamisetl_event_points(adapter)
    theirs = _kloppy_event_points(events_path, information_path)

    common = sorted(set(ours) & set(theirs))
    dynamisetl_only = sorted(set(ours) - set(theirs))
    kloppy_only = sorted(set(theirs) - set(ours))
    if not common:
        print("no common coordinate-bearing events; nothing to compare", file=sys.stderr)
        return 1

    max_dx = max(abs(ours[key][0] - theirs[key][0]) for key in common)
    max_dy = max(abs(ours[key][1] - theirs[key][1]) for key in common)
    squared = [
        (ours[key][0] - theirs[key][0]) ** 2 + (ours[key][1] - theirs[key][1]) ** 2
        for key in common
    ]
    rms_m = (sum(squared) / len(squared)) ** 0.5
    within_tolerance = max_dx <= args.tolerance_m and max_dy <= args.tolerance_m
    # Kloppy decodes provider Delete retractions (with coordinates) that
    # DynamisETL excludes explicitly; every remaining coordinate-bearing event
    # must match, and DynamisETL must not have produced coordinate events Kloppy
    # does not know about.
    deleted_with_coordinates = _count_deleted_events_with_coordinates(events_path)
    verdict = (
        "PASS"
        if (
            within_tolerance
            and not dynamisetl_only
            and len(kloppy_only) == deleted_with_coordinates
            and len(common) == len(ours)
        )
        else "FAIL"
    )

    bronze = {
        item.key: {
            "size_bytes": item.size_bytes,
            "local_sha256": item.local_sha256,
            "upstream_url": item.upstream_url,
        }
        for item in manifest.files
        if item.key in {events_key, information_key}
    }
    receipt = {
        "dataset_id": DATASET_ID,
        "version": args.version,
        "match": args.match,
        "generated_at": datetime.now(UTC).isoformat(),
        "kloppy_version": kloppy.__version__,
        "kloppy_pin": PINNED_KLOPPY_VERSION,
        "coordinate_systems": {
            "source": (
                "kloppy SportecEventDataCoordinateSystem "
                "(Origin.BOTTOM_LEFT, VerticalOrientation.BOTTOM_TO_TOP)"
            ),
            "target": (
                "kloppy SportecTrackingDataCoordinateSystem "
                "(Origin.CENTER, VerticalOrientation.BOTTOM_TO_TOP)"
            ),
            "dynamisetl": (
                "declared FrameTransform dfl-pitch-corner-m -> dfl-pitch-center-m "
                "(pure translation)"
            ),
        },
        "pitch_dimensions_m": [105.0, 68.0],
        "comparison_tolerance_m": args.tolerance_m,
        "counts": {
            "dynamisetl_coordinate_events": len(ours),
            "kloppy_coordinate_events": len(theirs),
            "compared_events": len(common),
            "dynamisetl_only_events": len(dynamisetl_only),
            "kloppy_only_events": len(kloppy_only),
            "deleted_events_with_coordinates": deleted_with_coordinates,
            "kloppy_only_note": (
                "Kloppy decodes provider Delete retraction events (with coordinates); "
                "DynamisETL excludes them explicitly."
            ),
        },
        "max_abs_delta_x_m": max_dx,
        "max_abs_delta_y_m": max_dy,
        "rms_m": rms_m,
        "bronze": bronze,
        "bronze_verified": True,
        "verdict": verdict,
    }
    target = receipt_path(
        resolved, dataset_id=DATASET_ID, kind="coordinate-oracle", name=f"{args.match}-events"
    )
    atomic_write_text(target, json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    if args.as_json:
        print(json.dumps(receipt, indent=2, sort_keys=True))
    else:
        print(
            f"Sportec coordinate oracle [{verdict}]: compared={len(common)} "
            f"max|dx|={max_dx:.3e} m max|dy|={max_dy:.3e} m rms={rms_m:.3e} m "
            f"(kloppy {kloppy.__version__})"
        )
        print(f"  receipt: {target}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
