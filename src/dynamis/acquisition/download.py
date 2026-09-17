"""Bounded, verified, atomic native-file downloads.

Acquisition rules implemented here (RES-97 execution lock):

* registry-driven expectations are supplied by the caller, never re-declared;
* the payload streams to a deterministic ``<final>.partial`` sibling, so a
  partially downloaded file can never be mistaken for an accepted artifact;
* the canonical upstream checksum is verified before promotion; a checksum
  mismatch is a terminal integrity failure, never retried;
* only transport failures (connection reset, timeout, 429/5xx) are retried;
* promotion to the final Bronze path is an atomic ``os.replace``;
* the locally computed SHA-256 and MD5 are returned so the caller can record
  them in the Bronze manifest.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.exceptions import ChunkedEncodingError, ContentDecodingError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

DEFAULT_CONNECT_TIMEOUT_S = 15.0
DEFAULT_READ_TIMEOUT_S = 180.0
DEFAULT_CHUNK_SIZE = 1 << 20
DEFAULT_MAX_ATTEMPTS = 3
MAX_RETRY_AFTER_S = 60.0

#: HTTP statuses worth retrying: rate limiting and transient upstream errors.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

USER_AGENT = "DynamisETL/0.1 (scientific data acquisition; +https://github.com/Litju/DynamisETL)"

PARTIAL_SUFFIX = ".partial"


class DownloadError(RuntimeError):
    """Base class for acquisition failures."""


class TransportFailure(DownloadError):
    """The payload could not be transferred after bounded retries."""


class IntegrityFailure(DownloadError):
    """The payload was transferred but does not match its declared identity."""


class UpstreamDriftError(DownloadError):
    """The upstream record no longer matches the committed registry expectation."""


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    """Verified result of one native-file download."""

    key: str
    path: Path
    url: str
    size_bytes: int
    sha256: str
    sha1: str
    md5: str
    git_blob_sha1: str | None
    retrieved_at: datetime
    attempts: int


def git_blob_sha1_of(content: bytes) -> str:
    """Git blob identity (``sha1("blob <size>\\0" + content)``)."""
    header = f"blob {len(content)}\0".encode("ascii")
    digest = hashlib.sha1(header)
    digest.update(content)
    return digest.hexdigest()


def _retry_after_seconds(response: requests.Response) -> float:
    raw = response.headers.get("Retry-After")
    if not raw:
        return 1.0
    try:
        return min(max(float(raw), 0.0), MAX_RETRY_AFTER_S)
    except ValueError:
        return 1.0


def _require_https(url: str, *, allow_insecure: bool) -> None:
    scheme = urlparse(url).scheme.lower()
    if scheme == "https" or (allow_insecure and scheme == "http"):
        return
    raise UpstreamDriftError(f"refusing to download over {scheme!r}: {url}")


def _expected_size_hint(response: requests.Response, expected_size: int | None) -> None:
    """Fail fast when an uncompressed response advertises a different size."""
    if expected_size is None:
        return
    if response.headers.get("Content-Encoding", "identity").lower() not in {"identity", ""}:
        return
    raw = response.headers.get("Content-Length")
    if raw is None:
        return
    try:
        advertised = int(raw)
    except ValueError:
        return
    if advertised != expected_size:
        raise UpstreamDriftError(
            f"upstream advertises {advertised} bytes but the registry expects {expected_size}"
        )


def _verify(
    *,
    key: str,
    size_bytes: int,
    md5: str,
    sha1: str,
    sha256: str,
    git_blob_sha1: str | None,
    expected_size: int | None,
    expected_md5: str | None,
    expected_sha1: str | None,
    expected_sha256: str | None,
    expected_git_blob_sha1: str | None,
) -> None:
    if expected_size is not None and size_bytes != expected_size:
        raise IntegrityFailure(
            f"{key}: downloaded {size_bytes} bytes but the registry expects {expected_size}"
        )
    if expected_md5 is not None and md5 != expected_md5.lower():
        raise IntegrityFailure(f"{key}: MD5 mismatch (upstream {expected_md5}, local {md5})")
    if expected_sha256 is not None and sha256 != expected_sha256.lower():
        raise IntegrityFailure(
            f"{key}: SHA-256 mismatch (upstream {expected_sha256}, local {sha256})"
        )
    if expected_sha1 is not None and sha1 != expected_sha1.lower():
        raise IntegrityFailure(f"{key}: SHA-1 mismatch (upstream {expected_sha1}, local {sha1})")
    if expected_git_blob_sha1 is not None:
        if git_blob_sha1 is None:
            raise IntegrityFailure(f"{key}: git blob identity was requested but not computed")
        if git_blob_sha1 != expected_git_blob_sha1.lower():
            raise IntegrityFailure(
                f"{key}: git blob SHA-1 mismatch (upstream {expected_git_blob_sha1}, "
                f"local {git_blob_sha1})"
            )


@dataclass(frozen=True, slots=True)
class FileDigest:
    """Every digest of one local file computed in a single streaming pass."""

    size_bytes: int
    md5: str
    sha1: str
    sha256: str
    git_blob_sha1: str | None


def digest_file(
    path: Path,
    *,
    git_blob: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> FileDigest:
    """Digest a local file without loading it into memory."""
    md5_digest = hashlib.md5()
    sha1_digest = hashlib.sha1()
    sha256_digest = hashlib.sha256()
    blob_digest = hashlib.sha1()
    size = Path(path).stat().st_size
    if git_blob:
        blob_digest.update(f"blob {size}\0".encode("ascii"))
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            md5_digest.update(chunk)
            sha1_digest.update(chunk)
            sha256_digest.update(chunk)
            if git_blob:
                blob_digest.update(chunk)
    return FileDigest(
        size_bytes=size,
        md5=md5_digest.hexdigest(),
        sha1=sha1_digest.hexdigest(),
        sha256=sha256_digest.hexdigest(),
        git_blob_sha1=blob_digest.hexdigest() if git_blob else None,
    )


def download_verified(
    session: requests.Session,
    url: str,
    destination: Path,
    *,
    key: str | None = None,
    expected_size: int | None = None,
    expected_md5: str | None = None,
    expected_sha1: str | None = None,
    expected_sha256: str | None = None,
    expected_git_blob_sha1: str | None = None,
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    allow_insecure: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DownloadReceipt:
    """Download ``url`` to ``destination`` with verification and atomic promotion.

    ``expected_sha1`` is accepted for registry fidelity but only a git blob
    identity (``expected_git_blob_sha1``) is verifiable from the content stream;
    callers pass exactly one of them.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if expected_sha1 is not None and expected_git_blob_sha1 is not None:
        raise ValueError("pass either a content SHA-1 or a git blob identity, not both")
    if expected_git_blob_sha1 is not None and expected_size is None:
        raise ValueError("a git blob identity requires the expected size to prefix the header")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + PARTIAL_SUFFIX)
    name = key or target.name

    last_transport: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        partial.unlink(missing_ok=True)
        response: requests.Response | None = None
        _require_https(url, allow_insecure=allow_insecure)
        try:
            response = session.get(
                url,
                stream=True,
                timeout=(connect_timeout_s, read_timeout_s),
                allow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": "identity",
                },
            )
            if response.status_code in RETRYABLE_STATUS:
                wait = _retry_after_seconds(response)
                response.close()
                last_transport = TransportFailure(
                    f"{name}: upstream returned {response.status_code}; retrying in {wait:.1f}s"
                )
                if attempt < max_attempts:
                    sleep(wait)
                    continue
                raise last_transport
            if not response.ok:
                response.close()
                raise UpstreamDriftError(
                    f"{name}: upstream returned {response.status_code} for {url}"
                )
            _require_https(response.url, allow_insecure=allow_insecure)
            _expected_size_hint(response, expected_size)

            md5_digest = hashlib.md5()
            sha1_digest = hashlib.sha1()
            sha256_digest = hashlib.sha256()
            blob_digest = hashlib.sha1()
            if expected_git_blob_sha1 is not None:
                blob_digest.update(f"blob {expected_size}\0".encode("ascii"))
            written = 0
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
                    md5_digest.update(chunk)
                    sha1_digest.update(chunk)
                    sha256_digest.update(chunk)
                    if expected_git_blob_sha1 is not None:
                        blob_digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            response.close()
        except (
            RequestsConnectionError,
            RequestsTimeout,
            ChunkedEncodingError,
            ContentDecodingError,
        ) as exc:
            if response is not None:
                response.close()
            last_transport = TransportFailure(f"{name}: transport failure: {exc}")
            partial.unlink(missing_ok=True)
            if attempt < max_attempts:
                sleep(1.0 * attempt)
                continue
            raise last_transport from exc
        except Exception:
            partial.unlink(missing_ok=True)
            raise

        local_git_blob = blob_digest.hexdigest() if expected_git_blob_sha1 is not None else None
        try:
            _verify(
                key=name,
                size_bytes=written,
                md5=md5_digest.hexdigest(),
                sha1=sha1_digest.hexdigest(),
                sha256=sha256_digest.hexdigest(),
                git_blob_sha1=local_git_blob,
                expected_size=expected_size,
                expected_md5=expected_md5,
                expected_sha1=expected_sha1,
                expected_sha256=expected_sha256,
                expected_git_blob_sha1=expected_git_blob_sha1,
            )
        except IntegrityFailure:
            partial.unlink(missing_ok=True)
            raise

        os.replace(partial, target)
        return DownloadReceipt(
            key=name,
            path=target,
            url=url,
            size_bytes=written,
            sha256=sha256_digest.hexdigest(),
            sha1=sha1_digest.hexdigest(),
            md5=md5_digest.hexdigest(),
            git_blob_sha1=local_git_blob,
            retrieved_at=now(),
            attempts=attempt,
        )

    raise last_transport or TransportFailure(f"{name}: no download attempt was made")
