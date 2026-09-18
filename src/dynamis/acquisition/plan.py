"""Registry-driven acquisition planning.

A plan is the deterministic, auditable output of "what would be fetched":

    registry source/version/file selection
        -> license/acquisition gate
        -> canonical provider resolver
        -> resolved canonical URL + upstream identity per file
        -> byte estimate

Planning never writes anything, so ``dynamis-fetch --dry-run`` and the real
acquisition share one code path up to the first byte. A registry that no longer
matches the upstream record fails the plan (drift), and there is no implicit
"fetch everything" mode: the caller must name keys, a match pattern, or ``all``.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

import requests

from dynamis.acquisition.resolvers import (
    ProviderResolver,
    ResolverError,
    resolver_for,
)
from dynamis.contracts import DatasetRegistry, DatasetSource, DatasetVersion
from dynamis.registry import (
    RegistryError,
    assert_acquisition_acknowledged,
    latest_version,
    validate_registry,
)

DEFAULT_METADATA_TIMEOUT_S = (15.0, 60.0)

#: Selection modes that require an explicit caller decision.
SELECTION_KEYS = "keys"
SELECTION_MATCH = "match"
SELECTION_ALL = "all"


class PlanError(ValueError):
    """The requested acquisition cannot be planned as stated."""


@dataclass(frozen=True, slots=True)
class PlannedFile:
    key: str
    url: str
    size_bytes: int
    upstream_md5: str | None
    upstream_sha1: str | None
    upstream_sha256: str | None
    git_blob_sha1: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    """Everything a verified acquisition needs, resolved from the registry."""

    dataset_id: str
    version: str
    provider: str
    resolver: str
    license_identifier: str | None
    license_local_only: bool
    attribution_required: bool
    citation: str | None
    upstream_url: str
    selection: str
    files: tuple[PlannedFile, ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    @property
    def total_mib(self) -> float:
        return self.total_bytes / (1 << 20)

    @property
    def whole_version(self) -> bool:
        return self.selection in {SELECTION_MATCH, SELECTION_ALL} and len(self.files) > 0

    def describe(self) -> str:
        lines = [
            f"dataset_id: {self.dataset_id}",
            f"version: {self.version}",
            f"provider: {self.provider} (resolver={self.resolver})",
            f"license: {self.license_identifier or 'unclear'}"
            + (" [local-only]" if self.license_local_only else ""),
            f"plan: {len(self.files)} file(s), {self.total_bytes} bytes ({self.total_mib:.2f} MiB)",
        ]
        for item in self.files:
            identity = (
                item.upstream_sha256 or item.git_blob_sha1 or item.upstream_md5 or "(size only)"
            )
            lines.append(
                f"  {item.key}: {item.size_bytes} bytes identity={identity} url={item.url}"
            )
        return "\n".join(lines)


def select_keys(
    version: DatasetVersion,
    *,
    keys: Sequence[str] = (),
    match: Sequence[str] = (),
    all_files: bool = False,
) -> tuple[str, ...]:
    """Resolve the requested file selection against the declared version files."""
    declared = [item.key for item in version.retrieval.files]
    if all_files:
        return tuple(declared)
    if keys:
        unknown = sorted(set(keys) - set(declared))
        if unknown:
            raise PlanError(
                f"version {version.version!r} declares no file(s) {unknown}; available: {declared}"
            )
        return tuple(dict.fromkeys(keys))
    if match:
        if not all(pattern.strip() for pattern in match):
            raise PlanError("match patterns must be non-empty")
        selected = [key for key in declared if any(pattern in key for pattern in match)]
        if not selected:
            raise PlanError(
                f"no declared file of version {version.version!r} matches {list(match)}; "
                f"available: {declared}"
            )
        return tuple(selected)
    raise PlanError(
        "a file selection is mandatory: pass --key, --match or --all. Fetching is never implicit."
    )


def _selection_mode(
    *, keys: Sequence[str], match: Sequence[str], all_files: bool, count: int
) -> str:
    if all_files:
        return SELECTION_ALL
    if keys:
        return SELECTION_KEYS
    if match:
        return SELECTION_MATCH
    raise PlanError("unreachable selection state")  # pragma: no cover - guarded earlier


def plan_acquisition(
    dataset_id: str,
    *,
    version: str | None = None,
    keys: Sequence[str] = (),
    match: Sequence[str] = (),
    all_files: bool = False,
    registry: DatasetRegistry | None = None,
    session: requests.Session | None = None,
    timeout: tuple[float, float] = DEFAULT_METADATA_TIMEOUT_S,
    acknowledgements: Collection[str] = (),
) -> AcquisitionPlan:
    """Resolve a registry source into a canonical, revision-pinned fetch plan.

    ``acknowledgements`` carries source-specific eligibility acknowledgements.
    The gate fails closed before any resolver or metadata request runs, so an
    unacknowledged restricted source can never be planned, let alone fetched.
    """
    document = registry if registry is not None else validate_registry()
    try:
        source = document.source(dataset_id)
    except KeyError as exc:
        raise PlanError(f"registry has no dataset {dataset_id!r}") from exc
    try:
        selected_version = source.version(version) if version else latest_version(source)
    except KeyError as exc:
        raise PlanError(str(exc)) from exc

    assert_acquisition_acknowledged(source, acknowledgements)
    selected = select_keys(selected_version, keys=keys, match=match, all_files=all_files)
    mode = _selection_mode(keys=keys, match=match, all_files=all_files, count=len(selected))
    if not source.license.local_only and not source.license.identifier:
        raise PlanError(f"{dataset_id}: a non-local-only source must declare a license identifier")

    try:
        resolver: ProviderResolver = resolver_for(source)
    except ResolverError as exc:
        raise PlanError(str(exc)) from exc

    with_session = session is not None
    http = session if session is not None else requests.Session()
    try:
        resolved = resolver.resolve(
            http,
            source=source,
            version=selected_version,
            keys=selected,
            timeout=timeout,
        )
    finally:
        if not with_session:
            http.close()

    files = tuple(
        PlannedFile(
            key=item.key,
            url=item.url,
            size_bytes=item.size_bytes,
            upstream_md5=item.upstream_md5,
            upstream_sha1=item.upstream_sha1,
            upstream_sha256=item.upstream_sha256,
            git_blob_sha1=item.git_blob_sha1,
        )
        for item in resolved
    )
    return AcquisitionPlan(
        dataset_id=source.dataset_id,
        version=selected_version.version,
        provider=source.provider,
        resolver=resolver.name,
        license_identifier=source.license.identifier,
        license_local_only=source.license.local_only,
        attribution_required=source.license.attribution_required,
        citation=selected_version.citation,
        upstream_url=str(selected_version.upstream_url),
        selection=mode,
        files=files,
    )


def resolve_against_registry(plan: AcquisitionPlan, source: DatasetSource) -> None:
    """Final gate: every planned file must still be a declared registry file."""
    version = source.version(plan.version)
    declared = {item.key: item for item in version.retrieval.files}
    for item in plan.files:
        expectation = declared.get(item.key)
        if expectation is None:
            raise RegistryError(f"{plan.dataset_id}/{plan.version}: undeclared key {item.key!r}")
        if expectation.size_bytes is not None and expectation.size_bytes != item.size_bytes:
            raise RegistryError(
                f"{plan.dataset_id}/{plan.version}/{item.key}: plan size {item.size_bytes} "
                f"!= registry {expectation.size_bytes}"
            )
