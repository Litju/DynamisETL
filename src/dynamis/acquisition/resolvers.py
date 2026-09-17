"""Canonical provider resolvers.

A resolver turns a registry key into the canonical download URL for a *pinned*
upstream revision, and cross-checks the upstream record against the committed
registry expectation before any byte is fetched. A disagreement is registry
drift and fails the plan; it is never "resolved" silently.

Two providers are implemented for RES-97:

``ZenodoResolver``
    uses the public Records API (``/api/records/<id>``) of the record identified
    by the registry DOI; the canonical link is the API-provided file link, never
    a scraped web page.
``HuggingFaceResolver``
    uses the dataset API tree at the pinned commit revision. Large files are
    stored in LFS/Xet and expose an authoritative SHA-256; small files are plain
    git blobs whose identity is the git blob SHA-1 (``sha1("blob <n>\\0"+data)``),
    which the downloader verifies from the stream.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import requests

from dynamis.acquisition.download import USER_AGENT, UpstreamDriftError
from dynamis.contracts import DatasetSource, DatasetVersion, RetrievalFile

ZENODO_RECORD_API = "https://zenodo.org/api/records/{record_id}"
HUGGING_FACE_RESOLVE = "https://huggingface.co/datasets/{repo_id}/resolve/{revision}/{path}"
HUGGING_FACE_TREE_API = (
    "https://huggingface.co/api/datasets/{repo_id}/tree/{revision}?recursive=true&expand=true"
)

_PINNED_REVISION = re.compile(r"^[0-9a-f]{40}$")
_ZENODO_DOI = re.compile(r"^10\.5281/zenodo\.(?P<record>\d+)$")
_ZENODO_RECORD_URL = re.compile(r"zenodo\.org/(?:records|record)/(?P<record>\d+)")
_HF_DATASET_URL = re.compile(
    r"huggingface\.co/datasets/(?P<owner>[A-Za-z0-9._-]+)/(?P<name>[A-Za-z0-9._-]+)"
)


class ResolverError(ValueError):
    """The registry cannot be resolved to canonical upstream URLs."""


@dataclass(frozen=True, slots=True)
class ResolvedFile:
    """One registry key resolved to a canonical URL plus upstream identity."""

    key: str
    url: str
    size_bytes: int
    upstream_md5: str | None = None
    upstream_sha1: str | None = None
    upstream_sha256: str | None = None
    git_blob_sha1: str | None = None
    provider_metadata: Mapping[str, str] = field(default_factory=dict)


class ProviderResolver(Protocol):
    """Resolve registry keys to canonical, revision-pinned upstream files."""

    name: str

    def resolve(
        self,
        session: requests.Session,
        *,
        source: DatasetSource,
        version: DatasetVersion,
        keys: Sequence[str],
        timeout: tuple[float, float],
    ) -> tuple[ResolvedFile, ...]: ...


def _get_json(
    session: requests.Session,
    url: str,
    *,
    timeout: tuple[float, float],
) -> object:
    response = session.get(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        if not response.ok:
            raise ResolverError(
                f"upstream metadata request failed with {response.status_code}: {url}"
            )
        return response.json()
    finally:
        response.close()


def _require_mapping(payload: object, *, what: str) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        raise ResolverError(f"{what}: expected a JSON object, got {type(payload).__name__}")
    return payload


def _require_sequence(payload: object, *, what: str) -> Sequence[object]:
    if isinstance(payload, (str, bytes)) or not isinstance(payload, Sequence):
        raise ResolverError(f"{what}: expected a JSON array")
    return payload


def _cross_check(
    *,
    key: str,
    size_bytes: int | None,
    md5: str | None,
    sha256: str | None,
    git_blob_sha1: str | None,
    expected_size: int | None,
    expected_md5: str,
    expected_sha256: str,
    expected_git_blob_sha1: str,
) -> None:
    """Registry expectation vs upstream record. Any disagreement is drift.

    ``expected_git_blob_sha1`` is deliberately distinct from a content SHA-1:
    providers that expose a git object identity (Hugging Face non-LFS files)
    promise the git blob hash, not the hash of the raw bytes.
    """
    if expected_size is not None and size_bytes is not None and size_bytes != expected_size:
        raise UpstreamDriftError(f"{key}: upstream size {size_bytes} != registry {expected_size}")
    if expected_md5 != "unknown" and md5 is not None and md5.lower() != expected_md5.lower():
        raise UpstreamDriftError(f"{key}: upstream MD5 {md5} != registry {expected_md5}")
    if expected_sha256 != "unknown" and sha256 is not None:
        if sha256.lower() != expected_sha256.lower():
            raise UpstreamDriftError(
                f"{key}: upstream SHA-256 {sha256} != registry {expected_sha256}"
            )
    if expected_git_blob_sha1 != "unknown" and git_blob_sha1 is not None:
        if git_blob_sha1.lower() != expected_git_blob_sha1.lower():
            raise UpstreamDriftError(
                f"{key}: upstream git blob identity {git_blob_sha1} != "
                f"registry {expected_git_blob_sha1}"
            )


class ZenodoResolver:
    """Resolve files through the Zenodo Records API for the registry DOI."""

    name = "zenodo"

    def record_id(self, source: DatasetSource) -> str:
        if source.doi:
            match = _ZENODO_DOI.match(source.doi)
            if match:
                return match.group("record")
        for url in source.upstream_urls:
            match = _ZENODO_RECORD_URL.search(str(url))
            if match:
                return match.group("record")
        raise ResolverError(f"{source.dataset_id}: cannot derive a Zenodo record id")

    def resolve(
        self,
        session: requests.Session,
        *,
        source: DatasetSource,
        version: DatasetVersion,
        keys: Sequence[str],
        timeout: tuple[float, float],
    ) -> tuple[ResolvedFile, ...]:
        record_id = self.record_id(source)
        payload = _require_mapping(
            _get_json(
                session,
                ZENODO_RECORD_API.format(record_id=record_id),
                timeout=timeout,
            ),
            what=f"Zenodo record {record_id}",
        )
        raw_files = _require_sequence(payload.get("files", ()), what="Zenodo record files")
        index: dict[str, Mapping[str, object]] = {}
        for raw in raw_files:
            entry = _require_mapping(raw, what="Zenodo file entry")
            key = entry.get("key")
            if isinstance(key, str):
                index[key] = entry

        resolved: list[ResolvedFile] = []
        for key in keys:
            entry = index.get(key)
            if entry is None:
                raise ResolverError(
                    f"{source.dataset_id}: Zenodo record {record_id} exposes no file {key!r}"
                )
            links = _require_mapping(entry.get("links", {}), what=f"{key} links")
            url = links.get("content") or links.get("self")
            if not isinstance(url, str) or not url:
                raise ResolverError(f"{source.dataset_id}/{key}: Zenodo exposes no file link")
            raw_size = entry.get("size")
            size_bytes = int(raw_size) if isinstance(raw_size, (int, float)) else None
            checksum = entry.get("checksum")
            md5 = None
            if isinstance(checksum, str) and checksum.startswith("md5:"):
                md5 = checksum.removeprefix("md5:")
            expectation = _expectation(version, key)
            _cross_check(
                key=key,
                size_bytes=size_bytes,
                md5=md5,
                sha256=None,
                git_blob_sha1=None,
                expected_size=expectation.size_bytes,
                expected_md5=expectation.md5,
                expected_sha256=expectation.sha256,
                expected_git_blob_sha1="unknown",
            )
            if size_bytes is None:
                raise ResolverError(f"{source.dataset_id}/{key}: Zenodo exposes no size")
            resolved.append(
                ResolvedFile(
                    key=key,
                    url=url,
                    size_bytes=size_bytes,
                    upstream_md5=md5,
                    provider_metadata={"record": record_id},
                )
            )
        return tuple(resolved)


class HuggingFaceResolver:
    """Resolve files at a pinned Hugging Face dataset revision."""

    name = "huggingface"

    def repo_id(self, source: DatasetSource) -> str:
        for url in source.upstream_urls:
            match = _HF_DATASET_URL.search(str(url))
            if match:
                return f"{match.group('owner')}/{match.group('name')}"
        raise ResolverError(f"{source.dataset_id}: cannot derive a Hugging Face repo id")

    def revision(self, source: DatasetSource, version: DatasetVersion) -> str:
        revision = version.version
        if not _PINNED_REVISION.match(revision):
            raise ResolverError(
                f"{source.dataset_id}: revision {revision!r} is not a pinned 40-hex commit; "
                "revision pinning is mandatory for Hugging Face acquisition"
            )
        return revision

    def resolve(
        self,
        session: requests.Session,
        *,
        source: DatasetSource,
        version: DatasetVersion,
        keys: Sequence[str],
        timeout: tuple[float, float],
    ) -> tuple[ResolvedFile, ...]:
        repo_id = self.repo_id(source)
        revision = self.revision(source, version)
        raw_entries = _require_sequence(
            _get_json(
                session,
                HUGGING_FACE_TREE_API.format(repo_id=repo_id, revision=revision),
                timeout=timeout,
            ),
            what=f"Hugging Face tree {repo_id}@{revision}",
        )
        index: dict[str, Mapping[str, object]] = {}
        for raw in raw_entries:
            entry = _require_mapping(raw, what="Hugging Face tree entry")
            path = entry.get("path")
            if isinstance(path, str):
                index[path] = entry

        resolved: list[ResolvedFile] = []
        for key in keys:
            entry = index.get(key)
            if entry is None:
                raise ResolverError(
                    f"{source.dataset_id}: revision {revision} exposes no file {key!r}"
                )
            if entry.get("type") != "file":
                raise ResolverError(f"{source.dataset_id}/{key}: tree entry is not a file")
            raw_size = entry.get("size")
            size_bytes = int(raw_size) if isinstance(raw_size, (int, float)) else None
            if size_bytes is None:
                raise ResolverError(f"{source.dataset_id}/{key}: tree entry exposes no size")
            lfs = entry.get("lfs")
            sha256: str | None = None
            git_blob_sha1: str | None = None
            if isinstance(lfs, Mapping):
                oid = lfs.get("oid")
                if isinstance(oid, str) and len(oid) == 64:
                    sha256 = oid
            if sha256 is None:
                oid = entry.get("oid")
                if isinstance(oid, str) and len(oid) == 40:
                    git_blob_sha1 = oid
            expectation = _expectation(version, key)
            _cross_check(
                key=key,
                size_bytes=size_bytes,
                md5=None,
                sha256=sha256,
                git_blob_sha1=git_blob_sha1,
                expected_size=expectation.size_bytes,
                expected_md5=expectation.md5,
                expected_sha256=expectation.sha256,
                expected_git_blob_sha1=expectation.sha1,
            )
            resolved.append(
                ResolvedFile(
                    key=key,
                    url=HUGGING_FACE_RESOLVE.format(repo_id=repo_id, revision=revision, path=key),
                    size_bytes=size_bytes,
                    upstream_sha256=sha256,
                    git_blob_sha1=git_blob_sha1,
                    provider_metadata={"repo": repo_id, "revision": revision},
                )
            )
        return tuple(resolved)


def _expectation(version: DatasetVersion, key: str) -> RetrievalFile:
    for item in version.retrieval.files:
        if item.key == key:
            return item
    raise ResolverError(f"version {version.version!r} does not declare file {key!r}")


RESOLVERS: tuple[ProviderResolver, ...] = (ZenodoResolver(), HuggingFaceResolver())


def resolver_for(source: DatasetSource) -> ProviderResolver:
    """Select the resolver from the registry provider string (deterministic)."""
    provider = source.provider.strip().lower()
    if provider.startswith("zenodo"):
        return RESOLVERS[0]
    if "hugging" in provider:
        return RESOLVERS[1]
    raise ResolverError(
        f"{source.dataset_id}: no acquisition resolver is registered for provider "
        f"{source.provider!r}"
    )


def resolver_names(registry_sources: Iterable[DatasetSource]) -> dict[str, str]:
    """Provider-to-resolver audit map used by planning output and tests."""
    mapping: dict[str, str] = {}
    for source in registry_sources:
        try:
            mapping[source.dataset_id] = resolver_for(source).name
        except ResolverError:
            mapping[source.dataset_id] = "unresolved"
    return mapping
