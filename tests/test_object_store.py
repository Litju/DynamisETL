from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import requests

from dynamis.config import ConfigurationError
from dynamis.storage.control_plane import _positive_int
from dynamis.storage.object_store import (
    LocalObjectStore,
    ObjectMetadata,
    ObjectStoreError,
    S3ObjectStore,
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


def test_s3_rejects_unverified_existing_objects_and_redirects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"verified bytes")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    store = S3ObjectStore(
        endpoint="https://objects.example",
        bucket="private",
        access_key="access",
        secret_key="secret",
    )
    monkeypatch.setattr(store, "head", lambda _key: ObjectMetadata("key", 14, ""))
    with pytest.raises(ObjectStoreError, match="expected checksum"):
        store.put_file(source, key=immutable_object_key(checksum), checksum_sha256=checksum)

    response = requests.Response()
    response.status_code = 307
    response.headers["Location"] = "http://insecure.example/object"
    seen: dict[str, object] = {}

    def request(_method: str, _url: str, **kwargs: object) -> requests.Response:
        seen.update(kwargs)
        return response

    monkeypatch.setattr(store.session, "request", request)
    with pytest.raises(ObjectStoreError, match="redirect refused"):
        store._request("PUT", "key", body=b"secret", headers={"x-amz-meta-sha256": checksum})
    assert seen["allow_redirects"] is False


def test_s3_range_reads_validate_partial_response_and_materialize_by_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"range-backed-object"
    checksum = hashlib.sha256(data).hexdigest()
    store = S3ObjectStore(
        endpoint="https://objects.example",
        bucket="private",
        access_key="access",
        secret_key="secret",
    )
    range_requests: list[tuple[int, int | None]] = []
    monkeypatch.setattr(store, "head", lambda key: ObjectMetadata(key, len(data), checksum))

    def get_range(_key: str, start: int, end: int | None = None) -> bytes:
        range_requests.append((start, end))
        return data[start : end + 1 if end is not None else None]

    monkeypatch.setattr(store, "get_range", get_range)
    monkeypatch.setattr(store, "range_chunk_bytes", 5)
    destination = tmp_path / "cache" / "object.parquet"
    store.materialize(
        immutable_object_key(checksum),
        destination=destination,
        checksum_sha256=checksum,
        expected_size=len(data),
    )
    assert destination.read_bytes() == data
    assert range_requests == [(0, 4), (5, 9), (10, 14), (15, 18)]


def test_s3_range_read_rejects_full_response() -> None:
    store = S3ObjectStore(
        endpoint="https://objects.example",
        bucket="private",
        access_key="access",
        secret_key="secret",
    )
    response = requests.Response()
    response.status_code = 200
    response._content = b"entire object"
    store.session.request = lambda *_args, **_kwargs: response  # type: ignore[method-assign]

    with pytest.raises(ObjectStoreError, match="did not honor"):
        store.get_range("key", 0, 1)


def test_s3_range_read_requires_the_requested_content_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = S3ObjectStore(
        endpoint="https://objects.example",
        bucket="private",
        access_key="access",
        secret_key="secret",
    )
    response = requests.Response()
    response.status_code = 206
    response.headers["Content-Range"] = "bytes 2-4/10"
    response._content = b"cde"
    request_options: dict[str, object] = {}

    def request(_method: str, _url: str, **kwargs: object) -> requests.Response:
        request_options.update(kwargs)
        return response

    monkeypatch.setattr(store.session, "request", request)
    assert store.get_range("key", 2, 4) == b"cde"
    assert request_options["allow_redirects"] is False

    response.headers["Content-Range"] = "bytes 3-5/10"
    with pytest.raises(ObjectStoreError, match="invalid Content-Range"):
        store.get_range("key", 2, 4)


def test_invalid_pool_values_use_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DYNAMIS_DB_POOL_SIZE", "not-a-number")
    with pytest.raises(ConfigurationError, match="DYNAMIS_DB_POOL_SIZE"):
        _positive_int("DYNAMIS_DB_POOL_SIZE", 4)
