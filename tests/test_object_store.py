from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dynamis.storage.object_store import (
    LocalObjectStore,
    ObjectStoreError,
    S3ObjectStore,
    immutable_object_key,
)
from dynamis.storage.control_plane import _positive_int
from dynamis.config import ConfigurationError


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


def test_credentialed_s3_requires_https_except_loopback() -> None:
    with pytest.raises(ObjectStoreError, match="https"):
        S3ObjectStore(
            endpoint="http://object-store.example",
            bucket="private",
            access_key="access",
            secret_key="secret",
        )
    S3ObjectStore(
        endpoint="http://127.0.0.1:9000",
        bucket="private",
        access_key="access",
        secret_key="secret",
    )
    with pytest.raises(ObjectStoreError, match="absolute URL"):
        S3ObjectStore(
            endpoint="https://",
            bucket="private",
            access_key="access",
            secret_key="secret",
        )


def test_invalid_pool_values_use_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DYNAMIS_DB_POOL_SIZE", "not-a-number")
    with pytest.raises(ConfigurationError, match="DYNAMIS_DB_POOL_SIZE"):
        _positive_int("DYNAMIS_DB_POOL_SIZE", 4)
