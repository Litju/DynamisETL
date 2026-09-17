"""Materialize the deterministic synthetic fixtures as canonical Parquet.

Used for manual verification and by the Dagster synthetic assets. Never touches a
provider dataset: it writes only synthetic, analytically known streams.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from dynamis.contracts import Modality
from dynamis.fixtures.synthetic import ModalityFixture, all_fixtures
from dynamis.quality.checks import validate
from dynamis.storage.parquet import write_parquet_atomic


def select_fixtures(modalities: Sequence[str]) -> tuple[ModalityFixture, ...]:
    selected = all_fixtures()
    if not modalities:
        return selected
    wanted = {Modality(value) for value in modalities}
    chosen = tuple(item for item in selected if item.modality in wanted)
    missing = wanted - {item.modality for item in chosen}
    if missing:
        raise KeyError(f"no synthetic fixture for {sorted(value.value for value in missing)}")
    return chosen


def materialize(
    fixtures: Sequence[ModalityFixture],
    output_dir: Path,
    *,
    validate_first: bool = True,
) -> tuple[Path, ...]:
    """Write every fixture as Parquet+Zstd. Returns the written paths."""
    written: list[Path] = []
    for fixture in fixtures:
        if validate_first:
            violations = validate(fixture.table, fixture.schema)
            if violations:
                summary = "; ".join(f"{item.rule}: {item.detail}" for item in violations)
                raise ValueError(f"{fixture.name} violates its contract: {summary}")
        target = Path(output_dir) / f"{fixture.name}.parquet"
        artifact = write_parquet_atomic(fixture.table, target, relative_to=output_dir)
        print(
            f"{fixture.name}: rows={artifact.row_count} bytes={artifact.byte_size} "
            f"sha256={artifact.checksum_sha256[:16]}"
        )
        written.append(artifact.path)
    return tuple(written)


def main(argv: Sequence[str] | None = None) -> int:
    from dynamis.config import settings
    from dynamis.contracts import ArtifactLayer
    from dynamis.storage.paths import layer_dir

    parser = argparse.ArgumentParser(
        prog="dynamis-synthetic-materialize",
        description=(
            "Materialize deterministic synthetic canonical streams as Parquet+Zstd. "
            "Synthetic data only; no provider dataset is downloaded or read."
        ),
    )
    parser.add_argument("--out", type=Path, default=None, help="Output directory")
    parser.add_argument(
        "--modality",
        action="append",
        default=[],
        choices=[member.value for member in Modality],
        help="Restrict to one modality (repeatable). Defaults to every modality.",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Write without running the contract checks first (not recommended).",
    )
    args = parser.parse_args(argv)

    output_dir = args.out
    if output_dir is None:
        resolved = settings()
        output_dir = layer_dir(resolved, ArtifactLayer.TMP) / "synthetic"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        fixtures = select_fixtures(args.modality)
    except (KeyError, ValueError) as exc:
        print(f"synthetic materialization FAILED: {exc}", file=sys.stderr)
        return 1

    try:
        materialize(fixtures, output_dir, validate_first=not args.skip_validation)
    except ValueError as exc:
        print(f"synthetic materialization FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"materialized {len(fixtures)} synthetic stream(s) under {output_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via console script
    raise SystemExit(main())
