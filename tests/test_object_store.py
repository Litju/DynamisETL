from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from dynamis.storage.object_store import (
    LocalObjectStore,
    ObjectStoreError,
    VercelPrivateBlobStore,
    immutable_object_key,
)


class FakeBlobClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: list[dict[str, object]] = []
        self.downloads: list[dict[str, object]] = []

    def head(self, key: str):
        data = self.objects.get(key)
        return None if data is None else SimpleNamespace(size=len(data), etag="test-etag")

    def upload_file(self, local_path: Path, key: str, **options: object) -> None:
        self.uploads.append(options)
        if key in self.objects and not options.get("overwrite"):
            raise RuntimeError("immutable object already exists")
        self.objects[key] = Path(local_path).read_bytes()

    def download_file(self, key: str, local_path: Path, **options: object) -> str:
        self.downloads.append(options)
        Path(local_path).write_bytes(self.objects[key])
        return str(local_path)


def test_local_object_store_is_checksum_bound_and_range_readable(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"canonical-parquet-bytes")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    key = immutable_object_key(checksum)
    store = LocalObjectStore(tmp_path / "objects")

    metadata = store.put_file(source, key=key, checksum_sha256=checksum)
    assert metadata.sha256 == checksum
    assert store.head(key) == metadata
    assert store.get_range(key, 10, 16) == b"parquet"
    assert store.put_file(source, key=key, checksum_sha256=checksum) == metadata


def test_local_object_store_rejects_traversal_and_checksum_drift(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"bytes")
    store = LocalObjectStore(tmp_path / "objects")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ObjectStoreError):
        store.put_file(source, key="../escape", checksum_sha256=checksum)
    with pytest.raises(ObjectStoreError):
        store.put_file(source, key=immutable_object_key(checksum), checksum_sha256="0" * 64)


def test_private_blob_upload_is_immutable_and_reconciled(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"immutable parquet bytes")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    key = immutable_object_key(checksum)
    client = FakeBlobClient()
    store = VercelPrivateBlobStore(client)

    metadata = store.put_file(source, key=key, checksum_sha256=checksum)
    repeated = store.put_file(source, key=key, checksum_sha256=checksum)

    assert metadata == repeated
    assert metadata.sha256 == checksum
    assert metadata.size_bytes == source.stat().st_size
    assert client.objects[key] == source.read_bytes()
    assert len(client.uploads) == 1
    assert client.uploads[0]["access"] == "private"
    assert client.uploads[0]["overwrite"] is False
    assert client.uploads[0]["add_random_suffix"] is False


def test_private_blob_existing_bytes_and_cached_file_are_checksum_checked(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"verified immutable bytes")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    key = immutable_object_key(checksum)
    client = FakeBlobClient()
    client.objects[key] = b"x" * source.stat().st_size
    store = VercelPrivateBlobStore(client)

    with pytest.raises(ObjectStoreError, match="checksum mismatch"):
        store.put_file(source, key=key, checksum_sha256=checksum)

    client.objects[key] = source.read_bytes()
    destination = tmp_path / "cache" / "source.parquet"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"x" * source.stat().st_size)
    materialized = store.materialize(
        key,
        destination=destination,
        checksum_sha256=checksum,
        expected_size=source.stat().st_size,
    )
    assert materialized.read_bytes() == source.read_bytes()
    assert client.downloads[-1]["access"] == "private"


def test_private_blob_rejects_non_normalized_keys(tmp_path: Path) -> None:
    store = VercelPrivateBlobStore(FakeBlobClient())
    with pytest.raises(ObjectStoreError):
        store.head("sha256/../private.parquet")
