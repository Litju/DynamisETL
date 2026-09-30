"""Local development storage and Vercel Private Blob artifacts."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dynamis.config import Settings
from dynamis.storage.atomic import atomic_write_path, sha256_file
from dynamis.storage.paths import safe_upstream_key


class ObjectStoreError(RuntimeError):
    """Raised when an immutable artifact operation cannot be verified."""


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    key: str
    size_bytes: int
    sha256: str
    etag: str | None = None


def immutable_object_key(sha256: str, suffix: str = "parquet") -> str:
    digest = sha256.lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ObjectStoreError("immutable object keys require a 64-character SHA-256")
    try:
        clean_suffix = safe_upstream_key(suffix).as_posix()
    except ValueError as exc:
        raise ObjectStoreError("invalid immutable object suffix") from exc
    return f"sha256/{digest[:2]}/{digest}/{clean_suffix}"


def _safe_key(key: str) -> str:
    try:
        normalized = safe_upstream_key(key).as_posix()
    except ValueError as exc:
        raise ObjectStoreError("invalid object key") from exc
    if normalized != key:
        raise ObjectStoreError("object key is not normalized")
    return normalized


class LocalObjectStore:
    """Filesystem adapter for local development and deterministic tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put_file(self, source: Path, *, key: str, checksum_sha256: str) -> ObjectMetadata:
        target = self._target(key)
        if sha256_file(source) != checksum_sha256:
            raise ObjectStoreError(f"source checksum mismatch for {key}")
        if target.exists() and sha256_file(target) != checksum_sha256:
            raise ObjectStoreError(f"immutable object already exists with different bytes: {key}")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with atomic_write_path(target) as temporary:
                temporary.write_bytes(source.read_bytes())
        return ObjectMetadata(key, target.stat().st_size, checksum_sha256)

    def head(self, key: str) -> ObjectMetadata | None:
        target = self._target(key)
        if not target.is_file():
            return None
        return ObjectMetadata(key, target.stat().st_size, sha256_file(target))

    def get_bytes(self, key: str) -> bytes:
        return self._target(key).read_bytes()

    def get_range(self, key: str, start: int, end: int | None = None) -> bytes:
        if start < 0 or (end is not None and end < start):
            raise ObjectStoreError("invalid object byte range")
        data = self._target(key).read_bytes()
        return data[start:] if end is None else data[start : end + 1]

    def _target(self, key: str) -> Path:
        target = (self.root / _safe_key(key)).resolve()
        if not target.is_relative_to(self.root):
            raise ObjectStoreError("object key escapes the configured local store")
        return target


class VercelPrivateBlobStore:
    """Checksum-bound Parquet objects in a private Vercel Blob store."""

    def __init__(self, client=None) -> None:
        if client is None:
            try:
                from vercel.blob import BlobClient
            except ImportError as exc:
                raise ObjectStoreError("install the Vercel Python SDK to use Private Blob") from exc
            client = BlobClient()
        self.client = client

    def put_file(self, source: Path, *, key: str, checksum_sha256: str) -> ObjectMetadata:
        key = _safe_key(key)
        size = source.stat().st_size
        if sha256_file(source) != checksum_sha256:
            raise ObjectStoreError(f"source checksum mismatch for {key}")

        existing = self.head(key)
        if existing is not None:
            return self._verify_existing(key, checksum_sha256, size, existing.etag)

        content_type = {
            ".arrow": "application/vnd.apache.arrow.file",
            ".feather": "application/vnd.apache.arrow.file",
            ".json": "application/json",
        }.get(source.suffix.lower(), "application/vnd.apache.parquet")
        try:
            self.client.upload_file(
                source,
                key,
                access="private",
                content_type=content_type,
                add_random_suffix=False,
                overwrite=False,
            )
        except Exception as exc:
            # A concurrent idempotent seed may have won the create-only write.
            existing = self.head(key)
            if existing is None:
                raise ObjectStoreError("Vercel Private Blob upload failed") from exc
            return self._verify_existing(key, checksum_sha256, size, existing.etag)
        return self._verify_existing(key, checksum_sha256, size, None)

    def head(self, key: str) -> ObjectMetadata | None:
        key = _safe_key(key)
        try:
            result = self.client.head(key)
        except Exception as exc:
            from vercel.blob.errors import BlobNotFoundError

            if isinstance(exc, BlobNotFoundError):
                return None
            raise ObjectStoreError("Vercel Private Blob metadata read failed") from exc
        if result is None:
            return None
        return ObjectMetadata(key, int(result.size or 0), "")

    def materialize(
        self,
        key: str,
        *,
        destination: Path,
        checksum_sha256: str,
        expected_size: int,
    ) -> Path:
        key = _safe_key(key)
        if destination.is_file():
            if (
                destination.stat().st_size == expected_size
                and sha256_file(destination) == checksum_sha256
            ):
                return destination
            destination.unlink()

        with atomic_write_path(destination) as temporary:
            try:
                self.client.download_file(
                    key,
                    temporary,
                    access="private",
                    overwrite=True,
                    create_parents=True,
                )
            except Exception as exc:
                raise ObjectStoreError("Vercel Private Blob download failed") from exc
            if (
                not temporary.is_file()
                or temporary.stat().st_size != expected_size
                or sha256_file(temporary) != checksum_sha256
            ):
                raise ObjectStoreError(f"Vercel Private Blob checksum mismatch for {key}")
        return destination

    def get_bytes(self, key: str) -> bytes:
        key = _safe_key(key)
        with tempfile.TemporaryDirectory(prefix="dynamis-blob-read-") as directory:
            path = Path(directory) / "object"
            try:
                self.client.download_file(
                    key,
                    path,
                    access="private",
                    overwrite=True,
                    create_parents=True,
                )
            except Exception as exc:
                raise ObjectStoreError("Vercel Private Blob read failed") from exc
            return path.read_bytes()

    def _verify_existing(
        self, key: str, checksum_sha256: str, size: int, etag: str | None
    ) -> ObjectMetadata:
        metadata = self.head(key)
        if metadata is None or metadata.size_bytes != size:
            raise ObjectStoreError(f"Vercel Private Blob size mismatch for {key}")
        with tempfile.TemporaryDirectory(prefix="dynamis-blob-verify-") as directory:
            self.materialize(
                key,
                destination=Path(directory) / "artifact",
                checksum_sha256=checksum_sha256,
                expected_size=size,
            )
        return ObjectMetadata(key, size, checksum_sha256, etag or metadata.etag)


@lru_cache(maxsize=1)
def _vercel_blob_store() -> VercelPrivateBlobStore:
    return VercelPrivateBlobStore()


def object_store(settings: Settings) -> LocalObjectStore | VercelPrivateBlobStore:
    if settings.object_store_provider == "local":
        if os.environ.get("VERCEL") == "1" or os.environ.get("VERCEL_ENV") in {
            "preview",
            "production",
        }:
            raise ObjectStoreError("Vercel deployments must use private Blob storage")
        return LocalObjectStore(settings.dataset_root)
    if settings.object_store_provider == "vercel-blob":
        return _vercel_blob_store()
    raise ObjectStoreError("DYNAMIS_OBJECT_STORE_PROVIDER must be local or vercel-blob")
