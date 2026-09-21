"""Private local and S3-compatible immutable artifact stores.

The S3 adapter uses only S3-compatible primitives and AWS SigV4 signing, so R2
or another private provider can be selected without changing artifact identity
or rights/provenance semantics. No provider is contacted during import.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from dynamis.config import Settings
from dynamis.storage.atomic import sha256_file
from dynamis.storage.paths import safe_upstream_key


class ObjectStoreError(RuntimeError):
    """Raised when an immutable object operation cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    key: str
    size_bytes: int
    sha256: str
    etag: str | None = None


def immutable_object_key(sha256: str, suffix: str = "parquet") -> str:
    if len(sha256) != 64 or any(
        character not in "0123456789abcdef" for character in sha256.lower()
    ):
        raise ObjectStoreError("immutable object keys require a lowercase 64-character SHA-256")
    clean_suffix = safe_upstream_key(suffix).as_posix()
    return f"sha256/{sha256[:2]}/{sha256}/{clean_suffix}"


class LocalObjectStore:
    """Filesystem adapter used by local development and deterministic tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put_file(self, source: Path, *, key: str, checksum_sha256: str) -> ObjectMetadata:
        target = self._target(key)
        observed = sha256_file(source)
        if observed != checksum_sha256:
            raise ObjectStoreError(f"source checksum mismatch for {key}")
        if target.exists():
            if sha256_file(target) != checksum_sha256:
                raise ObjectStoreError(
                    f"immutable object already exists with different bytes: {key}"
                )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        return ObjectMetadata(key=key, size_bytes=target.stat().st_size, sha256=checksum_sha256)

    def head(self, key: str) -> ObjectMetadata | None:
        target = self._target(key)
        if not target.is_file():
            return None
        return ObjectMetadata(key=key, size_bytes=target.stat().st_size, sha256=sha256_file(target))

    def get_range(self, key: str, start: int, end: int | None = None) -> bytes:
        if start < 0 or (end is not None and end < start):
            raise ObjectStoreError("invalid object byte range")
        data = self._target(key).read_bytes()
        return data[start:] if end is None else data[start : end + 1]

    def _target(self, key: str) -> Path:
        try:
            relative = safe_upstream_key(key)
        except ValueError as exc:
            raise ObjectStoreError(f"invalid object key: {key!r}") from exc
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root):
            raise ObjectStoreError("object key escapes the configured local store")
        return target


class S3ObjectStore:
    """Private S3-compatible adapter for R2 and equivalent object planes."""

    service = "s3"

    def __init__(
        self, *, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str = "auto"
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ObjectStoreError("S3 object endpoint must be an absolute HTTP(S) URL")
        self.endpoint = endpoint.rstrip("/")
        self.bucket = safe_upstream_key(bucket).as_posix()
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.session = requests.Session()

    def put_file(self, source: Path, *, key: str, checksum_sha256: str) -> ObjectMetadata:
        data = source.read_bytes()
        observed = hashlib.sha256(data).hexdigest()
        if observed != checksum_sha256:
            raise ObjectStoreError(f"source checksum mismatch for {key}")
        existing = self.head(key)
        if existing is not None:
            if existing.sha256 not in {checksum_sha256, ""}:
                raise ObjectStoreError(
                    f"immutable object already exists with different bytes: {key}"
                )
            return existing
        response = self._request(
            "PUT",
            key,
            body=data,
            headers={
                "content-type": "application/octet-stream",
                "x-amz-meta-sha256": checksum_sha256,
            },
        )
        if response is None:
            raise ObjectStoreError(f"S3 PUT {key} returned no response")
        etag = response.headers.get("ETag")
        return ObjectMetadata(key=key, size_bytes=len(data), sha256=checksum_sha256, etag=etag)

    def head(self, key: str) -> ObjectMetadata | None:
        response = self._request("HEAD", key, allow_not_found=True)
        if response is None:
            return None
        sha256 = response.headers.get("x-amz-meta-sha256", "")
        return ObjectMetadata(
            key=key,
            size_bytes=int(response.headers.get("Content-Length", "0")),
            sha256=sha256,
            etag=response.headers.get("ETag"),
        )

    def get_range(self, key: str, start: int, end: int | None = None) -> bytes:
        if start < 0 or (end is not None and end < start):
            raise ObjectStoreError("invalid object byte range")
        range_value = f"bytes={start}-{'' if end is None else end}"
        response = self._request("GET", key, headers={"range": range_value})
        if response is None:
            raise ObjectStoreError(f"S3 GET {key} returned no response")
        return response.content

    def _request(
        self,
        method: str,
        key: str,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        allow_not_found: bool = False,
    ) -> requests.Response | None:
        relative = safe_upstream_key(key).as_posix()
        url = f"{self.endpoint}/{quote(self.bucket, safe='')}/{quote(relative, safe='/~-_.')}"
        request_headers = {key.lower(): value for key, value in (headers or {}).items()}
        now = datetime.now(UTC)
        payload_hash = hashlib.sha256(body).hexdigest()
        request_headers.update(
            {
                "host": urlparse(url).netloc,
                "x-amz-content-sha256": payload_hash,
                "x-amz-date": now.strftime("%Y%m%dT%H%M%SZ"),
            }
        )
        if not request_headers.get("x-amz-meta-sha256") and method == "PUT":
            raise ObjectStoreError("immutable S3 uploads require x-amz-meta-sha256")
        signed_headers = ";".join(sorted(request_headers))
        canonical_headers = "".join(
            f"{name}:{' '.join(value.strip().split())}\n"
            for name, value in sorted(request_headers.items())
        )
        canonical_request = "\n".join(
            (method, urlparse(url).path or "/", "", canonical_headers, signed_headers, payload_hash)
        )
        date_stamp = now.strftime("%Y%m%d")
        scope = f"{date_stamp}/{self.region}/{self.service}/aws4_request"
        signing_key = _signing_key(self.secret_key, date_stamp, self.region, self.service)
        signature = hmac.new(
            signing_key, _string_to_sign(now, scope, canonical_request).encode(), hashlib.sha256
        ).hexdigest()
        request_headers["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{scope}, SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        response = self.session.request(
            method, url, data=body if method == "PUT" else None, headers=request_headers, timeout=30
        )
        if allow_not_found and response.status_code == 404:
            return None
        if not response.ok:
            raise ObjectStoreError(f"S3 {method} {key} failed with HTTP {response.status_code}")
        return response


def object_store(settings: Settings) -> LocalObjectStore | S3ObjectStore:
    if settings.object_store_provider == "local":
        return LocalObjectStore(settings.dataset_root)
    endpoint = settings.object_store_endpoint
    bucket = settings.object_store_bucket
    access_key = settings.object_store_access_key
    secret_key = settings.object_store_secret_key
    if any(value is None or value == "" for value in (endpoint, bucket, access_key, secret_key)):
        raise ObjectStoreError(
            "S3 object store requires endpoint, bucket, access key, and secret key"
        )
    assert (
        endpoint is not None
        and bucket is not None
        and access_key is not None
        and secret_key is not None
    )
    return S3ObjectStore(
        endpoint=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        region=settings.object_store_region,
    )


def _signing_key(secret: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode(), date_stamp.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode(), hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def _string_to_sign(now: datetime, scope: str, canonical_request: str) -> str:
    return (
        "AWS4-HMAC-SHA256\n"
        + now.strftime("%Y%m%dT%H%M%SZ")
        + "\n"
        + scope
        + "\n"
        + hashlib.sha256(canonical_request.encode()).hexdigest()
    )
