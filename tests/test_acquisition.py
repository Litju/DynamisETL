"""Acquisition boundary: planning, verification, retries, immutability.

All tests are synthetic: a loopback HTTP server serves in-memory payloads and a
fake session serves provider metadata JSON. No external dataset is touched.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
import requests
from pydantic import HttpUrl, ValidationError

from dynamis.acquisition import (
    AcquisitionPlan,
    ImmutableArtifactError,
    IntegrityFailure,
    PlanError,
    PlannedFile,
    ResolverError,
    UpstreamDriftError,
    acquire,
    download_verified,
    git_blob_sha1_of,
    plan_acquisition,
    select_keys,
)
from dynamis.acquisition.resolvers import HuggingFaceResolver, ZenodoResolver
from dynamis.config import Settings
from dynamis.contracts import (
    DatasetSource,
    DatasetVersion,
    Modality,
    RetrievalFile,
    RetrievalState,
    RetrievalStatus,
)
from dynamis.storage.manifest import (
    BRONZE_MANIFEST_SCHEMA_VERSION,
    read_bronze_manifest,
)
from dynamis.storage.paths import (
    bronze_manifest_path,
    bronze_native_path,
    receipt_path,
    relative_posix,
)
from synthetic_providers import FakeSession, synthetic_license, synthetic_registry

PAYLOAD = b"dynamis-acquisition-payload-0123456789" * 64
PAYLOAD_MD5 = hashlib.md5(PAYLOAD).hexdigest()
PAYLOAD_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()

#: Deterministic acquisition (T1) and verification (T2) instants.
T1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
T2 = datetime(2026, 2, 2, 13, 30, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Loopback HTTP server
# ---------------------------------------------------------------------------


@dataclass
class Route:
    body: bytes = b""
    status: int = 200
    location: str | None = None
    fail_times: int = 0
    #: Simulate a server that closes the stream early without a length header.
    omit_content_length: bool = False


@dataclass
class ServerState:
    routes: dict[str, Route] = field(default_factory=dict)
    hits: Counter[str] = field(default_factory=Counter)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        state: ServerState = self.server.state  # type: ignore[attr-defined]
        state.hits[self.path] += 1
        route = state.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        if route.fail_times > 0:
            route.fail_times -= 1
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        if route.status in {301, 302, 307, 308}:
            self.send_response(route.status)
            self.send_header("Location", route.location or "/")
            self.end_headers()
            return
        self.send_response(route.status)
        self.send_header("Content-Type", "application/octet-stream")
        if route.omit_content_length:
            self.send_header("Connection", "close")
            self.close_connection = True
        else:
            self.send_header("Content-Length", str(len(route.body)))
        self.end_headers()
        self.wfile.write(route.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - http.server API
        return


@pytest.fixture
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    state = ServerState()
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(base_url=f"http://127.0.0.1:{server.server_port}", state=state)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


# ---------------------------------------------------------------------------
# Fake provider metadata session
# ---------------------------------------------------------------------------


def _planned_file(key: str, url: str, *, remote: bytes = PAYLOAD) -> PlannedFile:
    return PlannedFile(
        key=key,
        url=url,
        size_bytes=len(remote),
        upstream_md5=hashlib.md5(remote).hexdigest(),
        upstream_sha1=None,
        upstream_sha256=hashlib.sha256(remote).hexdigest(),
        git_blob_sha1=None,
    )


def _plan(
    files: tuple[PlannedFile, ...],
    *,
    dataset_id: str = "syn-provider",
    version: str = "v1",
) -> AcquisitionPlan:
    return AcquisitionPlan(
        dataset_id=dataset_id,
        version=version,
        provider="Zenodo",
        resolver="zenodo",
        license_identifier="CC-BY-4.0",
        license_local_only=False,
        attribution_required=True,
        citation="Synthetic citation.",
        upstream_url="https://zenodo.org/records/12345",
        selection="keys",
        files=files,
    )


# ---------------------------------------------------------------------------
# download_verified
# ---------------------------------------------------------------------------


def test_download_verifies_and_promotes_atomically(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    target = tmp_settings.dataset_root / "bronze" / "payload.bin"
    receipt = download_verified(
        _session(),
        f"{local_server.base_url}/file",
        target,
        key="payload.bin",
        expected_size=len(PAYLOAD),
        expected_md5=PAYLOAD_MD5,
        expected_sha256=PAYLOAD_SHA256,
        allow_insecure=True,
    )
    assert target.read_bytes() == PAYLOAD
    assert receipt.sha256 == PAYLOAD_SHA256
    assert receipt.md5 == PAYLOAD_MD5
    assert receipt.attempts == 1
    assert not (target.parent / (target.name + ".partial")).exists()
    assert local_server.state.hits["/file"] == 1


def test_corrupt_payload_is_rejected_without_retry(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/corrupt"] = Route(body=PAYLOAD + b"x")
    target = tmp_settings.dataset_root / "corrupt.bin"
    with pytest.raises(IntegrityFailure, match="mismatch"):
        download_verified(
            _session(),
            f"{local_server.base_url}/corrupt",
            target,
            key="corrupt.bin",
            expected_size=len(PAYLOAD) + 1,
            expected_md5=PAYLOAD_MD5,
            expected_sha256=PAYLOAD_SHA256,
            allow_insecure=True,
        )
    assert not target.exists()
    assert not (target.parent / (target.name + ".partial")).exists()
    assert local_server.state.hits["/corrupt"] == 1


def test_upstream_size_drift_fails_fast_without_writing(
    tmp_settings: Settings, local_server
) -> None:
    local_server.state.routes["/short"] = Route(body=PAYLOAD[:100])
    target = tmp_settings.dataset_root / "short.bin"
    with pytest.raises(UpstreamDriftError, match="bytes"):
        download_verified(
            _session(),
            f"{local_server.base_url}/short",
            target,
            key="short.bin",
            expected_size=len(PAYLOAD),
            allow_insecure=True,
        )
    assert local_server.state.hits["/short"] == 1
    assert not target.exists()


def test_truncated_body_is_rejected_by_size_after_streaming(
    tmp_settings: Settings, local_server
) -> None:
    local_server.state.routes["/truncated"] = Route(body=PAYLOAD[:100], omit_content_length=True)
    target = tmp_settings.dataset_root / "truncated.bin"
    with pytest.raises(IntegrityFailure, match="downloaded 100 bytes"):
        download_verified(
            _session(),
            f"{local_server.base_url}/truncated",
            target,
            key="truncated.bin",
            expected_size=len(PAYLOAD),
            allow_insecure=True,
        )
    assert local_server.state.hits["/truncated"] == 1
    assert not target.exists()


def test_transient_503_is_retried_then_succeeds(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/flaky"] = Route(body=PAYLOAD, fail_times=1)
    target = tmp_settings.dataset_root / "flaky.bin"
    receipt = download_verified(
        _session(),
        f"{local_server.base_url}/flaky",
        target,
        key="flaky.bin",
        expected_size=len(PAYLOAD),
        expected_sha256=PAYLOAD_SHA256,
        allow_insecure=True,
        sleep=lambda seconds: None,
    )
    assert receipt.attempts == 2
    assert local_server.state.hits["/flaky"] == 2
    assert target.read_bytes() == PAYLOAD


def test_missing_file_is_not_retried(tmp_settings: Settings, local_server) -> None:
    target = tmp_settings.dataset_root / "missing.bin"
    with pytest.raises(UpstreamDriftError, match="404"):
        download_verified(
            _session(),
            f"{local_server.base_url}/missing",
            target,
            key="missing.bin",
            expected_size=len(PAYLOAD),
            allow_insecure=True,
        )
    assert local_server.state.hits["/missing"] == 1


def test_http_is_rejected_unless_explicitly_allowed(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    with pytest.raises(UpstreamDriftError, match="refusing to download"):
        download_verified(
            _session(),
            f"{local_server.base_url}/file",
            tmp_settings.dataset_root / "insecure.bin",
            expected_size=len(PAYLOAD),
        )
    assert local_server.state.hits["/file"] == 0


def test_redirect_is_followed_intentionally(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/start"] = Route(status=302, location="/file")
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    target = tmp_settings.dataset_root / "redirect.bin"
    receipt = download_verified(
        _session(),
        f"{local_server.base_url}/start",
        target,
        expected_size=len(PAYLOAD),
        expected_sha256=PAYLOAD_SHA256,
        allow_insecure=True,
    )
    assert receipt.url.endswith("/start")
    assert target.read_bytes() == PAYLOAD
    assert local_server.state.hits["/start"] == 1
    assert local_server.state.hits["/file"] == 1


def test_git_blob_identity_is_verified(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/blob"] = Route(body=PAYLOAD)
    target = tmp_settings.dataset_root / "blob.bin"
    receipt = download_verified(
        _session(),
        f"{local_server.base_url}/blob",
        target,
        expected_size=len(PAYLOAD),
        expected_git_blob_sha1=git_blob_sha1_of(PAYLOAD),
        allow_insecure=True,
    )
    assert receipt.git_blob_sha1 == git_blob_sha1_of(PAYLOAD)

    other = tmp_settings.dataset_root / "blob-bad.bin"
    with pytest.raises(IntegrityFailure, match="git blob SHA-1 mismatch"):
        download_verified(
            _session(),
            f"{local_server.base_url}/blob",
            other,
            expected_size=len(PAYLOAD),
            expected_git_blob_sha1="0" * 40,
            allow_insecure=True,
        )
    assert not other.exists()


def http_url(url: str) -> HttpUrl:
    return HttpUrl(url)


def _session():

    session = requests.Session()
    session.trust_env = False
    return session


# ---------------------------------------------------------------------------
# Selection and planning
# ---------------------------------------------------------------------------


def _version(files: tuple[RetrievalFile, ...], version: str = "v1") -> DatasetVersion:
    return DatasetVersion(
        version=version,
        upstream_url=http_url("https://zenodo.org/records/12345"),
        retrieval=RetrievalState(status=RetrievalStatus.NOT_FETCHED, files=files),
    )


def test_selection_is_never_implicit() -> None:
    version = _version((RetrievalFile(key="a.bin", size_bytes=1),))
    with pytest.raises(PlanError, match="selection is mandatory"):
        select_keys(version)


def test_selection_rejects_unknown_keys() -> None:
    version = _version((RetrievalFile(key="a.bin", size_bytes=1),))
    with pytest.raises(PlanError, match="declares no file"):
        select_keys(version, keys=["nope.bin"])


def test_selection_match_and_all_are_deterministic() -> None:
    files = (
        RetrievalFile(key="M01.xml", size_bytes=1),
        RetrievalFile(key="M02.xml", size_bytes=1),
        RetrievalFile(key="other.xml", size_bytes=1),
    )
    version = _version(files)
    assert select_keys(version, match=["M0"]) == ("M01.xml", "M02.xml")
    assert select_keys(version, all_files=True) == ("M01.xml", "M02.xml", "other.xml")
    assert select_keys(version, keys=["other.xml", "M01.xml"]) == ("other.xml", "M01.xml")
    with pytest.raises(PlanError, match="matches"):
        select_keys(version, match=["absent"])


def test_zenodo_plan_uses_the_records_api_and_detects_drift() -> None:
    files = (RetrievalFile(key="J01.xlsx", size_bytes=len(PAYLOAD), md5=PAYLOAD_MD5),)
    registry = synthetic_registry(files=files)
    api_url = "https://zenodo.org/api/records/12345"
    session = FakeSession(
        {
            api_url: {
                "files": [
                    {
                        "key": "J01.xlsx",
                        "size": len(PAYLOAD),
                        "checksum": f"md5:{PAYLOAD_MD5}",
                        "links": {
                            "self": "https://zenodo.org/api/records/12345/files/J01.xlsx/content"
                        },
                    }
                ]
            }
        }
    )
    plan = plan_acquisition("syn-provider", keys=["J01.xlsx"], registry=registry, session=session)
    assert session.calls == [api_url]
    assert plan.files[0].url.endswith("/J01.xlsx/content")
    assert plan.files[0].upstream_md5 == PAYLOAD_MD5
    assert plan.total_bytes == len(PAYLOAD)

    drifted = FakeSession(
        {
            api_url: {
                "files": [
                    {
                        "key": "J01.xlsx",
                        "size": len(PAYLOAD) + 1,
                        "checksum": f"md5:{PAYLOAD_MD5}",
                        "links": {
                            "self": "https://zenodo.org/api/records/12345/files/J01.xlsx/content"
                        },
                    }
                ]
            }
        }
    )
    with pytest.raises(UpstreamDriftError, match="upstream size"):
        plan_acquisition("syn-provider", keys=["J01.xlsx"], registry=registry, session=drifted)


def test_hugging_face_resolver_promotes_lfs_and_git_blob_identities() -> None:
    revision = "a" * 40
    big = b"positions" * 100
    small = b"<MatchInformation/>"
    files = (
        RetrievalFile(
            key="positions.xml", size_bytes=len(big), sha256=hashlib.sha256(big).hexdigest()
        ),
        RetrievalFile(key="info.xml", size_bytes=len(small), sha1=git_blob_sha1_of(small)),
    )
    registry = synthetic_registry(
        files=files,
        provider="Hugging Face (pysport)",
        upstream_urls=(http_url("https://huggingface.co/datasets/pysport/idsse-data"),),
        doi=None,
    )
    registry = registry.model_copy(
        update={
            "sources": (
                registry.sources[0].model_copy(
                    update={
                        "versions": (
                            registry.sources[0]
                            .versions[0]
                            .model_copy(update={"version": revision}),
                        )
                    }
                ),
            )
        }
    )
    session = FakeSession(
        {
            f"https://huggingface.co/api/datasets/pysport/idsse-data/tree/{revision}"
            "?recursive=true&expand=true": [
                {
                    "type": "file",
                    "path": "positions.xml",
                    "size": len(big),
                    "oid": "b" * 40,
                    "lfs": {"oid": hashlib.sha256(big).hexdigest(), "size": len(big)},
                },
                {
                    "type": "file",
                    "path": "info.xml",
                    "size": len(small),
                    "oid": git_blob_sha1_of(small),
                    "lfs": None,
                },
            ]
        }
    )
    plan = plan_acquisition(
        "syn-provider",
        keys=["positions.xml", "info.xml"],
        registry=registry,
        session=session,
    )
    assert plan.files[0].upstream_sha256 == hashlib.sha256(big).hexdigest()
    assert plan.files[1].git_blob_sha1 == git_blob_sha1_of(small)
    assert plan.files[0].url == (
        f"https://huggingface.co/datasets/pysport/idsse-data/resolve/{revision}/positions.xml"
    )


def test_hugging_face_resolver_requires_a_pinned_revision() -> None:
    registry = synthetic_registry(
        files=(RetrievalFile(key="positions.xml", size_bytes=10),),
        provider="Hugging Face (pysport)",
        upstream_urls=(http_url("https://huggingface.co/datasets/pysport/idsse-data"),),
        doi=None,
    )
    registry = registry.model_copy(
        update={
            "sources": (
                registry.sources[0].model_copy(
                    update={
                        "versions": (
                            registry.sources[0].versions[0].model_copy(update={"version": "main"}),
                        )
                    }
                ),
            )
        }
    )
    resolver = HuggingFaceResolver()
    with pytest.raises(ResolverError, match="revision pinning is mandatory"):
        resolver.resolve(
            FakeSession({}),
            source=registry.sources[0],
            version=registry.sources[0].versions[0],
            keys=["positions.xml"],
            timeout=(1.0, 1.0),
        )


def test_zenodo_resolver_requires_a_record_identity() -> None:
    source = DatasetSource(
        dataset_id="syn-provider",
        name="Synthetic",
        provider="Zenodo",
        upstream_urls=(http_url("https://example.org/elsewhere"),),
        doi=None,
        domain="football",
        modalities=(Modality.GNSS,),
        adapter_id="syn",
        v1_role="test",
        initial_scope="test",
        license=synthetic_license(),
    )
    with pytest.raises(ResolverError, match="record id"):
        ZenodoResolver().resolve(
            FakeSession({}),
            source=source,
            version=_version((RetrievalFile(key="a.bin", size_bytes=1),)),
            keys=["a.bin"],
            timeout=(1.0, 1.0),
        )


# ---------------------------------------------------------------------------
# acquire: Bronze promotion, manifest, receipt, idempotence
# ---------------------------------------------------------------------------


def test_acquire_promotes_bronze_and_is_idempotent(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    key = "payload.bin"
    registry = synthetic_registry(
        files=(
            RetrievalFile(
                key=key,
                size_bytes=len(PAYLOAD),
                md5=PAYLOAD_MD5,
                sha256=PAYLOAD_SHA256,
            ),
        )
    )
    plan = _plan((_planned_file(key, f"{local_server.base_url}/file"),), dataset_id="syn-provider")

    first = acquire(tmp_settings, plan, session=_session(), registry=registry, allow_insecure=True)
    assert first.downloaded == (key,)
    assert first.bytes_downloaded == len(PAYLOAD)
    assert first.manifest_verified

    final = bronze_native_path(tmp_settings, dataset_id="syn-provider", version="v1", key=key)
    assert final.read_bytes() == PAYLOAD
    manifest = read_bronze_manifest(tmp_settings, dataset_id="syn-provider", version="v1")
    assert manifest.files[0].local_sha256 == PAYLOAD_SHA256
    assert manifest.files[0].size_bytes == len(PAYLOAD)
    assert manifest.files[0].upstream_url == plan.files[0].url
    assert manifest.retrieved_at is not None

    hits_before = local_server.state.hits["/file"]
    second = acquire(tmp_settings, plan, session=_session(), registry=registry, allow_insecure=True)
    assert second.already_present == (key,)
    assert second.bytes_downloaded == 0
    assert local_server.state.hits["/file"] == hits_before


def test_verified_rerun_preserves_retrieval_and_advances_verification(
    tmp_settings: Settings, local_server
) -> None:
    """A verified no-download rerun must not restamp the acquisition instant."""
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    key = "payload.bin"
    registry = synthetic_registry(
        files=(RetrievalFile(key=key, size_bytes=len(PAYLOAD), sha256=PAYLOAD_SHA256),)
    )
    plan = _plan((_planned_file(key, f"{local_server.base_url}/file"),))

    first = acquire(
        tmp_settings,
        plan,
        session=_session(),
        registry=registry,
        allow_insecure=True,
        now=lambda: T1,
    )
    assert first.retrieval_performed
    assert first.retrieved_at == T1
    assert first.verified_at == T1

    final = bronze_native_path(tmp_settings, dataset_id="syn-provider", version="v1", key=key)
    bytes_at_t1 = final.read_bytes()
    hits_before = local_server.state.hits["/file"]

    second = acquire(
        tmp_settings,
        plan,
        session=_session(),
        registry=registry,
        allow_insecure=True,
        now=lambda: T2,
    )
    assert second.already_present == (key,)
    assert second.bytes_downloaded == 0
    assert not second.retrieval_performed
    assert local_server.state.hits["/file"] == hits_before  # zero HTTP payload requests
    assert final.read_bytes() == bytes_at_t1  # bytes unchanged

    manifest = read_bronze_manifest(tmp_settings, dataset_id="syn-provider", version="v1")
    assert manifest.schema_version == BRONZE_MANIFEST_SCHEMA_VERSION
    assert manifest.files[0].local_sha256 == PAYLOAD_SHA256  # digest unchanged
    assert manifest.files[0].retrieved_at == T1  # acquisition instant immutable
    assert manifest.files[0].verified_at == T2  # verification advances
    assert manifest.retrieved_at == T1
    assert manifest.verified_at == T2
    assert second.retrieved_at == T1
    assert second.verified_at == T2

    receipt_file = receipt_path(
        tmp_settings, dataset_id="syn-provider", kind="acquisition", name="v1"
    )
    payload = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert payload["retrieved_at"] == T1.isoformat()
    assert payload["verified_at"] == T2.isoformat()
    assert payload["retrieval_performed"] is False
    assert payload["bytes_downloaded"] == 0
    assert payload["files"][0]["retrieved_at"] == T1.isoformat()
    assert payload["files"][0]["verified_at"] == T2.isoformat()


def test_partial_acquisition_preserves_earlier_provenance(
    tmp_settings: Settings, local_server
) -> None:
    """Adding a file later must not erase the earlier file's acquisition facts."""
    local_server.state.routes["/a"] = Route(body=PAYLOAD)
    local_server.state.routes["/b"] = Route(body=PAYLOAD + b"-second")
    registry = synthetic_registry(
        files=(
            RetrievalFile(key="a.bin", size_bytes=len(PAYLOAD), sha256=PAYLOAD_SHA256),
            RetrievalFile(
                key="b.bin",
                size_bytes=len(PAYLOAD) + 7,
                sha256=hashlib.sha256(PAYLOAD + b"-second").hexdigest(),
            ),
        )
    )
    plan_a = _plan((_planned_file("a.bin", f"{local_server.base_url}/a"),))
    first = acquire(
        tmp_settings,
        plan_a,
        session=_session(),
        registry=registry,
        allow_insecure=True,
        now=lambda: T1,
    )
    assert first.downloaded == ("a.bin",)

    final_a = bronze_native_path(tmp_settings, dataset_id="syn-provider", version="v1", key="a.bin")
    bytes_at_t1 = final_a.read_bytes()
    hits_a_before = local_server.state.hits["/a"]

    plan_ab = _plan(
        (
            _planned_file("a.bin", f"{local_server.base_url}/a"),
            _planned_file("b.bin", f"{local_server.base_url}/b", remote=PAYLOAD + b"-second"),
        )
    )
    second = acquire(
        tmp_settings,
        plan_ab,
        session=_session(),
        registry=registry,
        allow_insecure=True,
        now=lambda: T2,
    )
    assert second.downloaded == ("b.bin",)
    assert second.already_present == ("a.bin",)
    assert local_server.state.hits["/a"] == hits_a_before
    assert final_a.read_bytes() == bytes_at_t1

    manifest = read_bronze_manifest(tmp_settings, dataset_id="syn-provider", version="v1")
    by_key = {item.key: item for item in manifest.files}
    assert by_key["a.bin"].retrieved_at == T1
    assert by_key["a.bin"].verified_at == T2
    assert by_key["b.bin"].retrieved_at == T2
    assert by_key["b.bin"].verified_at == T2
    # The version first entered Bronze at T1; the partial acquisition must not
    # move that forward just because its own run happened at T2.
    assert manifest.retrieved_at == T1
    assert manifest.verified_at == T2


def test_v1_manifest_stays_readable_and_upgrades_without_reinterpreting_history(
    tmp_settings: Settings, local_server
) -> None:
    """RES-97 Bronze manifests (schema 1) must keep working, values untouched."""
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    key = "payload.bin"
    registry = synthetic_registry(
        files=(RetrievalFile(key=key, size_bytes=len(PAYLOAD), sha256=PAYLOAD_SHA256),)
    )
    final = bronze_native_path(tmp_settings, dataset_id="syn-provider", version="v1", key=key)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(PAYLOAD)
    legacy_path = bronze_manifest_path(tmp_settings, dataset_id="syn-provider", version="v1")
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "dataset_id": "syn-provider",
                "version": "v1",
                "upstream_url": "https://zenodo.org/records/12345",
                "retrieved_at": T1.isoformat(),
                "files": [
                    {
                        "key": key,
                        "size_bytes": len(PAYLOAD),
                        "upstream_md5": PAYLOAD_MD5,
                        "upstream_sha1": None,
                        "upstream_sha256": PAYLOAD_SHA256,
                        "local_sha256": PAYLOAD_SHA256,
                        "retrieved_at": T1.isoformat(),
                        "upstream_url": f"{local_server.base_url}/file",
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = read_bronze_manifest(tmp_settings, dataset_id="syn-provider", version="v1")
    assert loaded.schema_version == "1"
    assert loaded.retrieved_at == T1
    assert loaded.files[0].retrieved_at == T1
    assert loaded.files[0].verified_at is None

    plan = _plan((_planned_file(key, f"{local_server.base_url}/file"),))
    receipt = acquire(
        tmp_settings,
        plan,
        session=_session(),
        registry=registry,
        allow_insecure=True,
        now=lambda: T2,
    )
    assert receipt.already_present == (key,)
    upgraded = read_bronze_manifest(tmp_settings, dataset_id="syn-provider", version="v1")
    assert upgraded.schema_version == BRONZE_MANIFEST_SCHEMA_VERSION
    assert upgraded.files[0].retrieved_at == T1  # original retrieval fact retained
    assert upgraded.files[0].verified_at == T2
    assert upgraded.retrieved_at == T1
    assert upgraded.verified_at == T2

    # A future/unknown schema is refused loudly instead of being reinterpreted.
    payload = json.loads(legacy_path.read_text(encoding="utf-8"))
    payload["schema_version"] = "99"
    legacy_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError, match="unsupported Bronze manifest schema_version"):
        read_bronze_manifest(tmp_settings, dataset_id="syn-provider", version="v1")


def test_receipt_is_written_outside_the_repository_without_absolute_paths(
    tmp_settings: Settings, local_server
) -> None:
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    key = "payload.bin"
    registry = synthetic_registry(
        files=(RetrievalFile(key=key, size_bytes=len(PAYLOAD), sha256=PAYLOAD_SHA256),)
    )
    plan = _plan((_planned_file(key, f"{local_server.base_url}/file"),))
    acquire(tmp_settings, plan, session=_session(), registry=registry, allow_insecure=True)

    receipt_file = receipt_path(
        tmp_settings, dataset_id="syn-provider", kind="acquisition", name="v1"
    )
    assert receipt_file.is_file()
    assert receipt_file.as_posix().startswith(tmp_settings.dataset_root.as_posix())
    payload = json.loads(receipt_file.read_text(encoding="utf-8"))
    assert payload["files"][0]["sha256"] == PAYLOAD_SHA256
    assert payload["manifest"]["verified"] is True
    assert str(tmp_settings.dataset_root) not in receipt_file.read_text(encoding="utf-8")


def test_acquire_refuses_to_overwrite_tampered_bronze(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    key = "payload.bin"
    registry = synthetic_registry(
        files=(RetrievalFile(key=key, size_bytes=len(PAYLOAD), sha256=PAYLOAD_SHA256),)
    )
    final = bronze_native_path(tmp_settings, dataset_id="syn-provider", version="v1", key=key)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"tampered")

    plan = _plan((_planned_file(key, f"{local_server.base_url}/file"),))
    with pytest.raises(ImmutableArtifactError, match="refusing to overwrite"):
        acquire(tmp_settings, plan, session=_session(), registry=registry, allow_insecure=True)
    assert final.read_bytes() == b"tampered"
    assert local_server.state.hits["/file"] == 0


def test_acquire_does_not_mutate_registry_state(tmp_settings: Settings, local_server) -> None:
    local_server.state.routes["/file"] = Route(body=PAYLOAD)
    key = "payload.bin"
    registry = synthetic_registry(
        files=(RetrievalFile(key=key, size_bytes=len(PAYLOAD), sha256=PAYLOAD_SHA256),)
    )
    before = registry.model_dump_json()
    plan = _plan((_planned_file(key, f"{local_server.base_url}/file"),))
    acquire(tmp_settings, plan, session=_session(), registry=registry, allow_insecure=True)
    assert registry.model_dump_json() == before
    assert registry.sources[0].versions[0].retrieval.status is RetrievalStatus.NOT_FETCHED


def test_bronze_key_with_subdirectory_is_preserved(tmp_settings: Settings, local_server) -> None:
    body = b"nested"
    local_server.state.routes["/nested"] = Route(body=body)
    key = "data/hp.csv"
    registry = synthetic_registry(
        files=(
            RetrievalFile(key=key, size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest()),
        )
    )
    plan = _plan((_planned_file(key, f"{local_server.base_url}/nested", remote=body),))
    acquire(tmp_settings, plan, session=_session(), registry=registry, allow_insecure=True)
    final = bronze_native_path(tmp_settings, dataset_id="syn-provider", version="v1", key=key)
    assert final.read_bytes() == body
    assert relative_posix(tmp_settings.dataset_root, final) == "bronze/syn-provider/v1/data/hp.csv"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_requires_an_explicit_selection(capsys: pytest.CaptureFixture[str]) -> None:
    from dynamis.acquisition.cli import main

    assert main(["dfl-sportec-idsse", "--dry-run"]) == 2
    assert "selection is mandatory" in capsys.readouterr().err


def test_cli_dry_run_plans_without_acquiring(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from dynamis.acquisition import cli

    plan = _plan(
        (
            PlannedFile(
                key="J01.xlsx",
                url="https://zenodo.org/api/records/10913119/files/J01.xlsx/content",
                size_bytes=29048182,
                upstream_md5="6ed03e071775ffb20ea649b1145bf380",
                upstream_sha1=None,
                upstream_sha256=None,
                git_blob_sha1=None,
            ),
        )
    )
    monkeypatch.setattr(cli, "plan_acquisition", lambda *a, **k: plan)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("dry-run must never acquire")

    monkeypatch.setattr(cli, "acquire", forbidden)
    assert cli.main(["womens-soccer-positioning", "--key", "J01.xlsx", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "J01.xlsx" in out
    assert "dry-run: nothing fetched" in out
    assert "27.70" in out


def test_cli_json_dry_run_emits_the_plan(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from dynamis.acquisition import cli

    plan = _plan(
        (
            PlannedFile(
                key="J01.xlsx",
                url="https://zenodo.org/api/records/10913119/files/J01.xlsx/content",
                size_bytes=100,
                upstream_md5=None,
                upstream_sha1=None,
                upstream_sha256=None,
                git_blob_sha1=None,
            ),
        )
    )
    monkeypatch.setattr(cli, "plan_acquisition", lambda *a, **k: plan)
    assert cli.main(["womens-soccer-positioning", "--key", "J01.xlsx", "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"][0]["key"] == "J01.xlsx"
    assert payload["total_bytes"] == 100
