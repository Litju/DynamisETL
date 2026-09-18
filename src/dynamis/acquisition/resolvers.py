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

import base64
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
GITHUB_TREE_API = "https://api.github.com/repos/{repo_id}/git/trees/{revision}?recursive=1"
GITHUB_BLOB_API = "https://api.github.com/repos/{repo_id}/git/blobs/{sha}"
GITHUB_RAW = "https://raw.githubusercontent.com/{repo_id}/{revision}/{path}"
GITHUB_MEDIA = "https://media.githubusercontent.com/media/{repo_id}/{revision}/{path}"

#: Git LFS pointers are tiny text blobs; anything at most this size is inspected
#: through the blob API so an LFS file is never mistaken for its pointer.
LFS_POINTER_MAX_BYTES = 1024
LFS_POINTER_HEADER = "version https://git-lfs.github.com/spec/v1"

_PINNED_REVISION = re.compile(r"^[0-9a-f]{40}$")
_ZENODO_DOI = re.compile(r"^10\.5281/zenodo\.(?P<record>\d+)$")
_ZENODO_RECORD_URL = re.compile(r"zenodo\.org/(?:records|record)/(?P<record>\d+)")
_HF_DATASET_URL = re.compile(
    r"huggingface\.co/datasets/(?P<owner>[A-Za-z0-9._-]+)/(?P<name>[A-Za-z0-9._-]+)"
)
_GITHUB_REPO_URL = re.compile(r"github\.com/(?P<owner>[A-Za-z0-9._-]+)/(?P<name>[A-Za-z0-9._-]+)")


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
        """Resolve record files and carry every known expectation forward.

        The provider exposes MD5 only. When the registry declares a SHA-256 the
        provider does not publish, that registry expectation is carried into the
        resolved file so the download is still verified against it; a registry
        expectation is never dropped just because the provider stays silent.
        """
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
                    upstream_md5=(
                        md5
                        if md5 is not None
                        else (None if expectation.md5 == "unknown" else expectation.md5)
                    ),
                    upstream_sha256=(
                        None if expectation.sha256 == "unknown" else expectation.sha256
                    ),
                    provider_metadata={"record": record_id},
                )
            )
        return tuple(resolved)


def _pinned_revision(*, dataset_id: str, revision: str, what: str) -> str:
    if not _PINNED_REVISION.match(revision):
        raise ResolverError(
            f"{dataset_id}: {what} {revision!r} is not a pinned 40-hex commit; "
            "revision pinning is mandatory"
        )
    return revision


def _hf_repo_id(source: DatasetSource) -> str:
    for url in source.upstream_urls:
        match = _HF_DATASET_URL.search(str(url))
        if match:
            return f"{match.group('owner')}/{match.group('name')}"
    raise ResolverError(f"{source.dataset_id}: cannot derive a Hugging Face repo id")


def _hf_tree_index(
    session: requests.Session,
    *,
    source: DatasetSource,
    repo_id: str,
    revision: str,
    timeout: tuple[float, float],
) -> dict[str, Mapping[str, object]]:
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
    return index


def _resolve_hf_files(
    *,
    source: DatasetSource,
    repo_id: str,
    revision: str,
    keys: Sequence[str],
    expectations: Mapping[str, RetrievalFile],
    index: Mapping[str, Mapping[str, object]],
) -> tuple[ResolvedFile, ...]:
    resolved: list[ResolvedFile] = []
    for key in keys:
        entry = index.get(key)
        if entry is None:
            raise ResolverError(f"{source.dataset_id}: revision {revision} exposes no file {key!r}")
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
        expectation = expectations[key]
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
                upstream_sha256=(
                    sha256
                    if sha256 is not None
                    else (None if expectation.sha256 == "unknown" else expectation.sha256)
                ),
                git_blob_sha1=(
                    git_blob_sha1
                    if git_blob_sha1 is not None
                    else (None if expectation.sha1 == "unknown" else expectation.sha1)
                ),
                provider_metadata={"repo": repo_id, "revision": revision},
            )
        )
    return tuple(resolved)


class HuggingFaceResolver:
    """Resolve files at a pinned Hugging Face dataset revision."""

    name = "huggingface"

    def repo_id(self, source: DatasetSource) -> str:
        return _hf_repo_id(source)

    def revision(self, source: DatasetSource, version: DatasetVersion) -> str:
        return _pinned_revision(
            dataset_id=source.dataset_id,
            revision=version.version,
            what="revision",
        )

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
        index = _hf_tree_index(
            session, source=source, repo_id=repo_id, revision=revision, timeout=timeout
        )
        return _resolve_hf_files(
            source=source,
            repo_id=repo_id,
            revision=revision,
            keys=keys,
            expectations={key: _expectation(version, key) for key in keys},
            index=index,
        )


def _parse_lfs_pointer(content: bytes, *, key: str) -> tuple[str, int] | None:
    """Return ``(sha256, size)`` when ``content`` is a Git LFS pointer."""
    try:
        lines = content.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError:
        return None
    if not lines or lines[0].strip() != LFS_POINTER_HEADER:
        return None
    oid: str | None = None
    size: int | None = None
    for line in lines[1:]:
        if line.startswith("oid sha256:"):
            oid = line.removeprefix("oid sha256:").strip()
        elif line.startswith("size "):
            try:
                size = int(line.removeprefix("size ").strip())
            except ValueError:
                size = None
    if oid is None or len(oid) != 64 or size is None:
        raise ResolverError(f"{key}: malformed Git LFS pointer; oid/size cannot be trusted")
    return oid, size


def _github_repo_id(source: DatasetSource) -> str:
    for url in source.upstream_urls:
        match = _GITHUB_REPO_URL.search(str(url))
        if match:
            return f"{match.group('owner')}/{match.group('name')}"
    raise ResolverError(f"{source.dataset_id}: cannot derive a GitHub repo id")


def _github_tree_index(
    session: requests.Session,
    *,
    source: DatasetSource,
    repo_id: str,
    revision: str,
    timeout: tuple[float, float],
) -> dict[str, Mapping[str, object]]:
    payload = _require_mapping(
        _get_json(
            session,
            GITHUB_TREE_API.format(repo_id=repo_id, revision=revision),
            timeout=timeout,
        ),
        what=f"GitHub tree {repo_id}@{revision}",
    )
    if payload.get("truncated"):
        raise ResolverError(
            f"{source.dataset_id}: GitHub tree at {revision} is truncated; refusing to "
            "resolve from an incomplete tree"
        )
    raw_entries = _require_sequence(payload.get("tree", ()), what="GitHub tree entries")
    index: dict[str, Mapping[str, object]] = {}
    for raw in raw_entries:
        entry = _require_mapping(raw, what="GitHub tree entry")
        path = entry.get("path")
        if isinstance(path, str):
            index[path] = entry
    return index


def _github_lfs_identity(
    session: requests.Session,
    *,
    source: DatasetSource,
    repo_id: str,
    key: str,
    blob_sha: str,
    timeout: tuple[float, float],
) -> tuple[str, int] | None:
    """Inspect a small blob through the API and parse an LFS pointer if present."""
    payload = _require_mapping(
        _get_json(
            session,
            GITHUB_BLOB_API.format(repo_id=repo_id, sha=blob_sha),
            timeout=timeout,
        ),
        what=f"GitHub blob {blob_sha}",
    )
    encoding = payload.get("encoding")
    content = payload.get("content")
    if encoding != "base64" or not isinstance(content, str):
        raise ResolverError(f"{source.dataset_id}/{key}: blob {blob_sha} exposes no base64 content")
    return _parse_lfs_pointer(base64.b64decode(content), key=key)


def _resolve_github_files(
    *,
    session: requests.Session,
    source: DatasetSource,
    repo_id: str,
    revision: str,
    keys: Sequence[str],
    expectations: Mapping[str, RetrievalFile],
    index: Mapping[str, Mapping[str, object]],
    timeout: tuple[float, float],
) -> tuple[ResolvedFile, ...]:
    resolved: list[ResolvedFile] = []
    for key in keys:
        entry = index.get(key)
        if entry is None:
            raise ResolverError(f"{source.dataset_id}: revision {revision} exposes no file {key!r}")
        if entry.get("type") != "blob":
            raise ResolverError(f"{source.dataset_id}/{key}: tree entry is not a blob")
        raw_size = entry.get("size")
        size_bytes = int(raw_size) if isinstance(raw_size, (int, float)) else None
        blob_sha = entry.get("sha")
        if size_bytes is None or not isinstance(blob_sha, str):
            raise ResolverError(f"{source.dataset_id}/{key}: tree entry exposes no identity")
        expectation = expectations[key]
        lfs: tuple[str, int] | None = None
        # A declared SHA-256 must be verified against real content; a tiny blob
        # with a declared SHA-256 may be a Git LFS pointer and is always
        # inspected through the API before choosing the download host.
        if size_bytes <= LFS_POINTER_MAX_BYTES and expectation.sha256 != "unknown":
            lfs = _github_lfs_identity(
                session,
                source=source,
                repo_id=repo_id,
                key=key,
                blob_sha=blob_sha,
                timeout=timeout,
            )
        if lfs is not None:
            oid, pointer_size = lfs
            _cross_check(
                key=key,
                size_bytes=pointer_size,
                md5=None,
                sha256=oid,
                git_blob_sha1=blob_sha,
                expected_size=expectation.size_bytes,
                expected_md5=expectation.md5,
                expected_sha256=expectation.sha256,
                expected_git_blob_sha1=expectation.sha1,
            )
            resolved.append(
                ResolvedFile(
                    key=key,
                    url=GITHUB_MEDIA.format(repo_id=repo_id, revision=revision, path=key),
                    size_bytes=pointer_size,
                    upstream_sha256=oid,
                    provider_metadata={
                        "repo": repo_id,
                        "revision": revision,
                        "storage": "git-lfs",
                        "pointer_sha": blob_sha,
                    },
                )
            )
            continue
        _cross_check(
            key=key,
            size_bytes=size_bytes,
            md5=None,
            sha256=None,
            git_blob_sha1=blob_sha,
            expected_size=expectation.size_bytes,
            expected_md5=expectation.md5,
            expected_sha256=expectation.sha256,
            expected_git_blob_sha1=expectation.sha1,
        )
        resolved.append(
            ResolvedFile(
                key=key,
                url=GITHUB_RAW.format(repo_id=repo_id, revision=revision, path=key),
                size_bytes=size_bytes,
                upstream_sha256=(None if expectation.sha256 == "unknown" else expectation.sha256),
                git_blob_sha1=blob_sha,
                provider_metadata={
                    "repo": repo_id,
                    "revision": revision,
                    "storage": "git",
                },
            )
        )
    return tuple(resolved)


class GitHubResolver:
    """Resolve files at a pinned GitHub revision, following Git LFS pointers."""

    name = "github"

    def repo_id(self, source: DatasetSource) -> str:
        return _github_repo_id(source)

    def revision(self, source: DatasetSource, version: DatasetVersion) -> str:
        return _pinned_revision(
            dataset_id=source.dataset_id,
            revision=version.version,
            what="revision",
        )

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
        index = _github_tree_index(
            session, source=source, repo_id=repo_id, revision=revision, timeout=timeout
        )
        return _resolve_github_files(
            session=session,
            source=source,
            repo_id=repo_id,
            revision=revision,
            keys=keys,
            expectations={key: _expectation(version, key) for key in keys},
            index=index,
            timeout=timeout,
        )


def _routed_provider(expectation: RetrievalFile, *, key: str) -> str:
    provider = (expectation.upstream_provider or "").strip().lower()
    if provider.startswith("hugging"):
        return "huggingface"
    if provider.startswith("github"):
        return "github"
    raise ResolverError(
        f"file {key!r} declares unsupported upstream_provider "
        f"{expectation.upstream_provider!r}; supported: github, huggingface"
    )


class RoutedResolver:
    """Route each file to its declared companion provider at a pinned revision.

    A multi-provider dataset (match metadata in GitHub, body-pose archive in a
    Hugging Face release) resolves every selected file through its explicit
    ``upstream_provider``/``upstream_revision`` declaration. No provider is
    guessed from prose, and a companion file without a pinned revision fails.
    """

    name = "routed"

    def resolve(
        self,
        session: requests.Session,
        *,
        source: DatasetSource,
        version: DatasetVersion,
        keys: Sequence[str],
        timeout: tuple[float, float],
    ) -> tuple[ResolvedFile, ...]:
        expectations = {key: _expectation(version, key) for key in keys}
        routed: dict[str, list[str]] = {"github": [], "huggingface": []}
        for key in keys:
            routed[_routed_provider(expectations[key], key=key)].append(key)
        resolved: list[ResolvedFile] = []
        if routed["github"]:
            repo_id = _github_repo_id(source)
            revision = _pinned_revision(
                dataset_id=source.dataset_id,
                revision=version.version,
                what="revision",
            )
            index = _github_tree_index(
                session, source=source, repo_id=repo_id, revision=revision, timeout=timeout
            )
            resolved.extend(
                _resolve_github_files(
                    session=session,
                    source=source,
                    repo_id=repo_id,
                    revision=revision,
                    keys=routed["github"],
                    expectations=expectations,
                    index=index,
                    timeout=timeout,
                )
            )
        if routed["huggingface"]:
            repo_id = _hf_repo_id(source)
            revisions: set[str] = set()
            for key in routed["huggingface"]:
                expectation = expectations[key]
                if expectation.upstream_revision is None:
                    raise ResolverError(
                        f"{source.dataset_id}/{key}: a companion Hugging Face file requires "
                        "an explicit pinned upstream_revision"
                    )
                revisions.add(
                    _pinned_revision(
                        dataset_id=source.dataset_id,
                        revision=expectation.upstream_revision,
                        what="upstream_revision",
                    )
                )
            if len(revisions) != 1:
                raise ResolverError(
                    f"{source.dataset_id}: Hugging Face files declare different revisions "
                    f"{sorted(revisions)}; one pinned companion revision per resolution is "
                    "required"
                )
            revision = revisions.pop()
            index = _hf_tree_index(
                session, source=source, repo_id=repo_id, revision=revision, timeout=timeout
            )
            resolved.extend(
                _resolve_hf_files(
                    source=source,
                    repo_id=repo_id,
                    revision=revision,
                    keys=routed["huggingface"],
                    expectations=expectations,
                    index=index,
                )
            )
        order = {key: index for index, key in enumerate(keys)}
        return tuple(sorted(resolved, key=lambda item: order[item.key]))


def _expectation(version: DatasetVersion, key: str) -> RetrievalFile:
    for item in version.retrieval.files:
        if item.key == key:
            return item
    raise ResolverError(f"version {version.version!r} does not declare file {key!r}")


RESOLVERS: tuple[ProviderResolver, ...] = (
    ZenodoResolver(),
    HuggingFaceResolver(),
    GitHubResolver(),
    RoutedResolver(),
)


def resolver_for(source: DatasetSource) -> ProviderResolver:
    """Select the resolver from the registry provider and file declarations.

    A source whose files declare companion providers is routed per file; a plain
    Hugging Face or Zenodo source keeps its single-provider resolver. Selection is
    deterministic and never inferred from a URL that the registry did not declare.
    """
    routed = any(
        item.upstream_provider is not None
        for version in source.versions
        for item in version.retrieval.files
    )
    if routed:
        return RESOLVERS[3]
    provider = source.provider.strip().lower()
    if provider.startswith("zenodo"):
        return RESOLVERS[0]
    if "hugging" in provider:
        return RESOLVERS[1]
    if "github" in provider or "skillcorner" in provider:
        return RESOLVERS[2]
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
