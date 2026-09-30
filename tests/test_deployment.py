from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from infra.deploy import promote_neon
from infra.deploy.promote_neon import _connection, _identity
from infra.deploy.release_gate import check_evidence
from infra.deploy.seed import run as seed_deployment
from infra.deploy.upload_artifacts import _assert_registry_rights
from infra.deploy.verify_artifact_receipt import (
    compare_receipts,
)
from infra.deploy.verify_artifact_receipt import (
    verify as verify_artifact_receipt,
)
from sqlalchemy.engine import URL

from dynamis.config import ConfigurationError
from dynamis.deployment import (
    DeploymentError,
    load_public_demo_resources,
    load_public_seed,
    public_rights_error,
    rights_allowlist_sha256,
)
from dynamis.deployment_manifest import load_manifest, manifest_key, parse_manifest
from dynamis.serving import cli
from dynamis.serving.app import create_app, serving_exposure
from dynamis.storage.object_store import LocalObjectStore, immutable_object_key


def _receipt(environment: str, sha: str, objects: list[dict] | None = None) -> dict:
    demo = load_public_demo_resources()
    if objects is None:
        checksum = "b" * 64
        objects = [
            {
                "environment": environment,
                "git_sha": sha,
                "dataset_id": demo[0].dataset_id,
                "checksum_sha256": checksum,
                "object_key": immutable_object_key(checksum),
                "size_bytes": 8,
                "source_kinds": ["sample"],
                "artifact_ids": ["artifact-a"],
            }
        ]
    return {
        "schema_version": 1,
        "environment": environment,
        "git_sha": sha,
        "manifest_key": manifest_key(environment, sha),
        "rights_allowlist_sha256": rights_allowlist_sha256(),
        "allowlisted_datasets": sorted(seed.dataset_id for seed in load_public_seed()),
        "demo_resources": [
            {
                "dataset_id": item.dataset_id,
                "session_id": item.session_id,
                "worlds": list(item.worlds),
            }
            for item in demo
        ],
        "object_count": len(objects),
        "byte_count": sum(item["size_bytes"] for item in objects),
        "objects": objects,
    }


def _license(**overrides):
    values = {
        "status": "declared",
        "identifier": "CC-BY-4.0",
        "attribution_required": False,
        "redistribution": "conditional",
        "local_only": False,
        "noncommercial_only": False,
        "share_alike": False,
        "restrictions": (),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_public_seed_is_explicit_and_excludes_restricted_sources():
    seeds = load_public_seed()
    ids = {seed.dataset_id for seed in seeds}

    assert ids == {
        "white-cmj-acc-grf",
        "dfl-sportec-idsse",
        "skillcorner-opendata",
        "skillcorner-basketball-opendata",
    }
    assert "sportsdataverse" not in ids
    assert "tackle-workload" not in ids
    assert "womens-soccer-positioning" not in ids
    assert "spl-open-data" not in ids
    assert "openbiomechanics" not in ids
    assert [(item.dataset_id, item.session_id) for item in load_public_demo_resources()] == [
        ("skillcorner-basketball-opendata", "114243")
    ]


def test_production_gate_requires_all_preview_checks(tmp_path):
    path = tmp_path / "release.json"
    sha = "a" * 40
    receipt_path = tmp_path / "preview-artifacts.json"
    receipt_path.write_text(json.dumps(_receipt("preview", sha)), encoding="utf-8")
    evidence = {
        "environment": "preview",
        "git_sha": sha,
        "preview_url": "https://preview.example",
        "database_target_sha256": "c" * 64,
        "artifact_receipt": receipt_path.name,
        "gates": {
            "rights": "passed",
            "secrets": "passed",
            "migration": "passed",
            "object_reconciliation": "passed",
            "external_smoke": "passed",
        },
    }
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert check_evidence(path, sha) == ()
    evidence["gates"]["object_reconciliation"] = "blocked"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert check_evidence(path, sha) == ("object_reconciliation",)


def test_artifact_receipt_requires_checksum_bound_objects(tmp_path):
    sha = "a" * 40
    receipt = _receipt("preview", sha)
    path = tmp_path / "objects.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert verify_artifact_receipt(path, "preview", sha) == ()
    receipt["objects"][0]["object_key"] = "public/url"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert "object key is not checksum-bound" in verify_artifact_receipt(path, "preview", sha)[0]


def test_artifact_receipt_accepts_multiple_curated_objects(tmp_path):
    sha = "a" * 40
    dataset_id = load_public_demo_resources()[0].dataset_id
    objects = [
        {
            "environment": "preview",
            "git_sha": sha,
            "dataset_id": dataset_id,
            "checksum_sha256": checksum,
            "object_key": immutable_object_key(checksum),
            "size_bytes": index + 1,
            "source_kinds": ["sample"],
            "artifact_ids": [f"artifact-{index}"],
        }
        for index, checksum in enumerate(("b" * 64, "c" * 64))
    ]
    receipt = _receipt("preview", sha, objects)
    path = tmp_path / "objects.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert verify_artifact_receipt(path, "preview", sha) == ()
    assert parse_manifest(path.read_bytes(), "preview", sha) == frozenset(
        {"artifact-0", "artifact-1"}
    )


def test_manifest_loader_checks_that_every_listed_blob_object_exists(tmp_path):
    sha = "a" * 40
    body = b"curated-parquet-bytes"
    checksum = hashlib.sha256(body).hexdigest()
    store = LocalObjectStore(tmp_path / "blob")
    object_file = tmp_path / "object.parquet"
    object_file.write_bytes(body)
    receipt = _receipt(
        "preview",
        sha,
        [
            {
                "environment": "preview",
                "git_sha": sha,
                "dataset_id": load_public_demo_resources()[0].dataset_id,
                "checksum_sha256": checksum,
                "object_key": immutable_object_key(checksum),
                "size_bytes": len(body),
                "source_kinds": ["sample"],
                "artifact_ids": ["sample-1"],
            }
        ],
    )
    store.put_file(
        object_file,
        key=receipt["objects"][0]["object_key"],
        checksum_sha256=checksum,
    )
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(receipt), encoding="utf-8")
    store.put_file(
        manifest_file,
        key=manifest_key("preview", sha),
        checksum_sha256=hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
    )

    assert load_manifest(store, "preview", sha) == frozenset({"sample-1"})

    store._target(receipt["objects"][0]["object_key"]).unlink()
    with pytest.raises(DeploymentError, match="references missing"):
        load_manifest(store, "preview", sha)


def test_preview_and_production_blob_receipts_reconcile(tmp_path):
    sha = "a" * 40
    preview = tmp_path / "preview.json"
    production = tmp_path / "production.json"
    preview.write_text(json.dumps(_receipt("preview", sha)), encoding="utf-8")
    production.write_text(json.dumps(_receipt("production", sha)), encoding="utf-8")

    assert compare_receipts(preview, production, sha) == ()
    changed = _receipt("production", sha)
    changed["objects"][0]["checksum_sha256"] = "d" * 64
    changed["objects"][0]["object_key"] = immutable_object_key("d" * 64)
    production.write_text(json.dumps(changed), encoding="utf-8")
    assert compare_receipts(preview, production, sha) == (
        "production Blob objects do not match Preview",
    )


def test_neon_promotion_requires_distinct_project_branch_ids(monkeypatch):
    for name, value in {
        "DYNAMIS_PREVIEW_NEON_PROJECT_ID": "preview-project",
        "DYNAMIS_PREVIEW_NEON_BRANCH_ID": "preview-branch",
        "DYNAMIS_PRODUCTION_NEON_PROJECT_ID": "production-project",
        "DYNAMIS_PRODUCTION_NEON_BRANCH_ID": "production-branch",
    }.items():
        monkeypatch.setenv(name, value)
    assert _identity()["preview"]["project_id"] == "preview-project"
    monkeypatch.setenv("DYNAMIS_PRODUCTION_NEON_PROJECT_ID", "preview-project")
    monkeypatch.setenv("DYNAMIS_PRODUCTION_NEON_BRANCH_ID", "preview-branch")
    with pytest.raises(DeploymentError, match="must be distinct"):
        _identity()


def test_neon_promotion_rejects_pooled_endpoints_and_keeps_url_out_of_pg_args(monkeypatch):
    pooled = URL.create(
        "postgresql",
        username="role",
        password="test",
        host="ep-example-pooler.us-east-2.aws.neon.tech",
        database="db",
    )
    with pytest.raises(DeploymentError, match="direct, unpooled"):
        _connection(str(pooled))
    direct = URL.create(
        "postgresql",
        username="role",
        password="test",
        host="ep-example.us-east-2.aws.neon.tech",
        database="db",
        query={"sslmode": "require"},
    )
    monkeypatch.setenv("DYNAMIS_PREVIEW_DATABASE_URL", "omit-this-value")
    env, database = _connection(str(direct))

    assert database == "db"
    assert env["PGHOST"] == "ep-example.us-east-2.aws.neon.tech"
    assert env["PGDATABASE"] == "db"
    assert env["PGSSLMODE"] == "require"
    assert "PGPASSWORD" in env
    assert "DYNAMIS_PREVIEW_DATABASE_URL" not in env


def test_production_seed_requires_the_verified_neon_promoter(monkeypatch):
    monkeypatch.setenv("DYNAMIS_DEPLOY_ENV", "production")

    with pytest.raises(DeploymentError, match="infra.deploy.promote_neon"):
        seed_deployment(apply=True)


def test_neon_promotion_receipt_records_dump_database_and_blob_evidence(tmp_path, monkeypatch):
    sha = "a" * 40
    counts = {
        "table_count": 2,
        "row_count": 7,
        "gold_table_count": 1,
        "gold_row_count": 3,
        "table_rows": {"dynamis.dataset_source": 4, "gold.trial_metrics": 3},
        "gold_table_rows": {"gold.trial_metrics": 3},
    }
    neon_ids = {
        "preview": {"project_id": "preview-project", "branch_id": "preview-branch"},
        "production": {"project_id": "production-project", "branch_id": "production-branch"},
    }
    parity = {
        "passed": True,
        "object_count": 6,
        "preview_receipt_sha256": "b" * 64,
        "production_receipt_sha256": "c" * 64,
    }
    monkeypatch.setattr(
        promote_neon,
        "_preflight",
        lambda *_args: (
            sha,
            "dynamis",
            neon_ids,
            {"preview": "preview-url", "production": "production-url"},
            "gold",
            ("head1",),
            parity,
        ),
    )
    monkeypatch.setattr(promote_neon, "_heads", lambda *_args: ("head1",))
    monkeypatch.setattr(promote_neon, "database_counts", lambda *_args: counts)
    monkeypatch.setattr(promote_neon, "_connection", lambda _url: ({}, "dynamis"))
    monkeypatch.setattr(promote_neon.shutil, "which", lambda name: f"C:/tools/{name}.exe")

    def fake_run(args, _env, *, stdout=None):
        if args[0].endswith("pg_dump.exe"):
            Path(args[args.index("--file") + 1]).write_bytes(b"preview dump")

    monkeypatch.setattr(promote_neon, "_run", fake_run)
    receipt_path = tmp_path / "promotion.json"
    receipt = promote_neon.promote(
        apply=True,
        preview_receipt=tmp_path / "preview.json",
        production_receipt=tmp_path / "production.json",
        receipt_path=receipt_path,
    )

    assert receipt["neon"] == neon_ids
    assert receipt["git_sha"] == sha
    assert receipt["alembic_head"] == "head1"
    assert len(receipt["pg_dump_sha256"]) == 64
    assert receipt["preview_counts"]["row_count"] == 7
    assert receipt["production_before_counts"]["row_count"] == 7
    assert receipt["production_counts"]["gold_row_count"] == 3
    assert receipt["rights_allowlist_sha256"] == rights_allowlist_sha256()
    assert receipt["blob_receipt_parity"] == parity
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt


def test_public_rights_reject_local_unclear_and_noncommercial_sources():
    assert public_rights_error(_license()) is None
    assert public_rights_error(_license(local_only=True, redistribution="prohibited"))
    assert public_rights_error(_license(status="unclear", identifier=None))
    assert public_rights_error(_license(noncommercial_only=True))
    assert public_rights_error(None)


def test_upload_rights_must_match_every_registry_field():
    expected = _license(attribution_required=True, restrictions=("attribution required",))
    policy = _license(attribution_required=True, restrictions=["attribution required"])

    _assert_registry_rights("approved", policy, expected)
    with pytest.raises(DeploymentError, match="attribution_required"):
        _assert_registry_rights("approved", _license(), expected)


def test_preview_exposure_defaults_to_public(monkeypatch):
    monkeypatch.setenv("DYNAMIS_ENVIRONMENT", "preview")
    monkeypatch.delenv("DYNAMIS_SERVING_EXPOSURE", raising=False)

    assert serving_exposure() == "public"


def test_public_runtime_cannot_disable_rights_enforcement(monkeypatch):
    monkeypatch.setenv("DYNAMIS_ENVIRONMENT", "preview")
    monkeypatch.setenv("DYNAMIS_SERVING_EXPOSURE", "local")
    monkeypatch.setenv("DYNAMIS_TRUSTED_HOSTS", "api.example")
    monkeypatch.setenv("DYNAMIS_CORS_ORIGINS", "https://web.example")

    with pytest.raises(ConfigurationError, match="public rights enforcement"):
        create_app(backend=object())


def test_structured_access_logs_disable_plain_uvicorn_access_log(monkeypatch):
    monkeypatch.setenv("DYNAMIS_ACCESS_LOG", "1")
    called = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: called.update(kwargs))

    assert cli.main([]) == 0
    assert called["access_log"] is False


def test_api_security_headers_cors_and_trusted_hosts(monkeypatch):
    monkeypatch.setenv("DYNAMIS_CORS_ORIGINS", "https://web.example")
    app = create_app(backend=object())

    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Origin": "https://web.example"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://web.example"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-request-id"]
        rejected = client.get("/api/health", headers={"Host": "attacker.example"})
        assert rejected.status_code == 400


def test_public_artifact_route_blocks_restricted_dataset(monkeypatch):
    monkeypatch.setenv("DYNAMIS_ENVIRONMENT", "preview")
    monkeypatch.setenv("DYNAMIS_CORS_ORIGINS", "https://web.example")
    monkeypatch.setenv("DYNAMIS_TRUSTED_HOSTS", "testserver")
    monkeypatch.delenv("DYNAMIS_SERVING_EXPOSURE", raising=False)

    class Backend:
        def artifact(self, _artifact_id):
            return SimpleNamespace(dataset_id="sportsdataverse")

        def dataset(self, _dataset_id):
            return SimpleNamespace(license=_license(local_only=True, redistribution="prohibited"))

    with TestClient(create_app(backend=Backend()), raise_server_exceptions=False) as client:
        response = client.get("/api/artifacts/restricted/window")

    assert response.status_code == 451
    assert response.json()["state"] == "rights_restricted"


def test_public_artifact_route_blocks_bytes_missing_from_release_manifest(monkeypatch):
    monkeypatch.setenv("DYNAMIS_ENVIRONMENT", "preview")
    monkeypatch.setenv("DYNAMIS_CORS_ORIGINS", "https://web.example")
    monkeypatch.setenv("DYNAMIS_TRUSTED_HOSTS", "testserver")
    monkeypatch.delenv("DYNAMIS_SERVING_EXPOSURE", raising=False)

    class Backend:
        def artifact(self, _artifact_id):
            return SimpleNamespace(dataset_id="skillcorner-basketball-opendata")

        def dataset(self, _dataset_id):
            return SimpleNamespace(license=_license())

        def artifact_is_deployed(self, _artifact_id):
            return False

    with TestClient(create_app(backend=Backend()), raise_server_exceptions=False) as client:
        response = client.get("/api/artifacts/missing/window")

    assert response.status_code == 404
    assert response.json()["detail"].startswith("artifact bytes are not present")


def test_public_world_payload_route_blocks_manifest_incomplete_contest(monkeypatch):
    monkeypatch.setenv("DYNAMIS_ENVIRONMENT", "preview")
    monkeypatch.setenv("DYNAMIS_CORS_ORIGINS", "https://web.example")
    monkeypatch.setenv("DYNAMIS_TRUSTED_HOSTS", "testserver")
    monkeypatch.delenv("DYNAMIS_SERVING_EXPOSURE", raising=False)

    class Backend:
        def game_license(self, _contest_id):
            return _license()

        def world_is_deployed(self, _world, _resource_id):
            return False

        def basketball_spatial_game(self, _contest_id):
            raise AssertionError("incomplete World payload must not be opened")

    with TestClient(create_app(backend=Backend()), raise_server_exceptions=False) as client:
        response = client.get("/api/basketball/contests/not-ready")

    assert response.status_code == 404
    assert "private Blob manifest" in response.json()["detail"]


def test_internal_errors_do_not_echo_exception_text(monkeypatch):
    monkeypatch.setenv("DYNAMIS_CORS_ORIGINS", "https://web.example")

    class Backend:
        def datasets(self):
            raise RuntimeError("private error payload must not be exposed")

    with TestClient(create_app(backend=Backend()), raise_server_exceptions=False) as client:
        response = client.get("/api/catalog/datasets", headers={"Origin": "https://web.example"})

    assert response.status_code == 500
    assert response.json()["detail"] == "internal server error"
    assert "private error payload" not in response.text
    assert response.json()["request_id"]
    assert response.headers["x-request-id"]
    assert response.headers["access-control-allow-origin"] == "https://web.example"
