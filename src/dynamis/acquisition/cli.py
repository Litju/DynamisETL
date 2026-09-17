"""Registry-driven acquisition ``dynamis-fetch`` CLI.

Examples::

    dynamis-fetch womens-soccer-positioning --version 1.0 --key J01.xlsx --dry-run

    dynamis-fetch dfl-sportec-idsse \\
        --version a715a38dfbaf5f58e431727c2b78d174101a703c \\
        --match J03WPY

The CLI never fetches implicitly: a key, match pattern or ``--all`` is required,
and ``--dry-run`` prints the resolved plan with a byte estimate without writing
anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from dynamis.acquisition.download import DownloadError
from dynamis.acquisition.plan import AcquisitionPlan, PlanError, plan_acquisition
from dynamis.acquisition.resolvers import ResolverError
from dynamis.acquisition.runner import acquire
from dynamis.config import ConfigurationError, settings
from dynamis.registry import assert_registry_valid, load_registry, validate_registry

EXIT_OK = 0
EXIT_FAILURE = 2

LARGE_FETCH_BYTES = 8 << 20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dynamis-fetch",
        description=(
            "Plan and execute a verified, registry-driven acquisition from a canonical "
            "provider into immutable Bronze storage outside the repository. "
            "A file selection is mandatory; nothing is fetched implicitly."
        ),
    )
    parser.add_argument("dataset_id", help="Registry dataset_id to acquire")
    parser.add_argument("--version", default=None, help="Pinned version/revision (default: newest)")
    parser.add_argument(
        "--key",
        action="append",
        default=[],
        help="Exact upstream file key to fetch (repeatable)",
    )
    parser.add_argument(
        "--match",
        action="append",
        default=[],
        help="Fetch declared files whose key contains this substring (repeatable)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_files",
        help="Explicitly select every declared file of the version",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print the plan; download nothing",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit the machine-readable receipt (or plan) as JSON",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="Alternate registry.json path (defaults to the committed registry)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress the human-readable plan summary"
    )
    return parser


def _print_plan(plan: AcquisitionPlan, *, quiet: bool) -> None:
    if quiet:
        return
    print(plan.describe())
    if plan.total_bytes >= LARGE_FETCH_BYTES:
        print(
            f"note: this fetch is {plan.total_mib:.1f} MiB; Bronze files are written "
            "atomically and verified against upstream identity"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        registry = (
            validate_registry(args.registry)
            if args.registry is None
            else _validate_explicit_registry(args.registry)
        )
        plan = plan_acquisition(
            args.dataset_id,
            version=args.version,
            keys=args.key,
            match=args.match,
            all_files=args.all_files,
            registry=registry,
        )
    except (PlanError, ResolverError, DownloadError) as exc:
        print(f"dynamis-fetch: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    if args.dry_run:
        if args.as_json:
            print(json.dumps(_plan_payload(plan), indent=2, sort_keys=True))
        else:
            _print_plan(plan, quiet=args.quiet)
            print("dry-run: nothing fetched")
        return EXIT_OK

    try:
        resolved_settings = settings()
        receipt = acquire(resolved_settings, plan)
    except (ConfigurationError, DownloadError, OSError) as exc:
        print(f"dynamis-fetch: acquisition failed: {exc}", file=sys.stderr)
        return EXIT_FAILURE

    if args.as_json:
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
    else:
        _print_plan(plan, quiet=args.quiet)
        print(receipt.describe())
        if receipt.license_identifier and not receipt.license_local_only:
            print(
                f"license: {receipt.license_identifier} (attribution required: "
                f"{receipt.attribution_required})"
            )
    return EXIT_OK


def _validate_explicit_registry(path: Path):
    document = load_registry(path)
    assert_registry_valid(document)
    return document


def _plan_payload(plan: AcquisitionPlan) -> dict[str, object]:
    return {
        "dataset_id": plan.dataset_id,
        "version": plan.version,
        "provider": plan.provider,
        "resolver": plan.resolver,
        "license_identifier": plan.license_identifier,
        "license_local_only": plan.license_local_only,
        "selection": plan.selection,
        "total_bytes": plan.total_bytes,
        "files": [
            {
                "key": item.key,
                "url": item.url,
                "size_bytes": item.size_bytes,
                "upstream_md5": item.upstream_md5,
                "upstream_sha1": item.upstream_sha1,
                "upstream_sha256": item.upstream_sha256,
                "git_blob_sha1": item.git_blob_sha1,
            }
            for item in plan.files
        ],
    }


__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover - exercised via console script
    raise SystemExit(main())
