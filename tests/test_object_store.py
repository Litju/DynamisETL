from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dynamis.storage.object_store import (
    LocalObjectStore,
    ObjectStoreError,
    immutable_object_key,
)


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
