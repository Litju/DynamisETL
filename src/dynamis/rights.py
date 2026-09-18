"""Rights gate for local-only external sources.

Two independent obligations are enforced here:

* a source whose upstream record exposes no explicit license value (or whose
  redistribution is prohibited) must never have its raw or derived records
  materialized inside the repository, even on an ignored path;
* no export surface may publish or bundle such records at all.

The gate is deliberately conservative: it can only block, never relax. Being
stricter than a provider's eventual clarification is always safe; the reverse is
not.
"""

from __future__ import annotations

from pathlib import Path

from dynamis.config import repository_root
from dynamis.contracts import DatasetSource, RedistributionPolicy


class RightsError(RuntimeError):
    """A local-only or redistribution-prohibited source crossed a boundary."""


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def assert_dataset_root_outside_repository(source: DatasetSource, dataset_root: Path) -> None:
    """Raw/derived records of a local-only source must live outside the repository."""
    if not source.license.local_only:
        return
    if _is_within(Path(dataset_root), repository_root()):
        raise RightsError(
            f"{source.dataset_id}: local-only source data must not be materialized inside "
            f"the repository ({Path(dataset_root)} is within {repository_root()})"
        )


def assert_export_allowed(source: DatasetSource, destination: Path) -> None:
    """No export surface may emit records of a local-only/prohibited source."""
    if source.license.redistribution is RedistributionPolicy.PROHIBITED:
        raise RightsError(
            f"{source.dataset_id}: redistribution is prohibited; refusing to export to "
            f"{Path(destination).name!r}"
        )
    if source.license.local_only:
        raise RightsError(
            f"{source.dataset_id}: local-only source; refusing to export to "
            f"{Path(destination).name!r}"
        )


__all__ = [
    "RightsError",
    "assert_dataset_root_outside_repository",
    "assert_export_allowed",
]
