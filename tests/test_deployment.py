from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from infra.deploy.release_gate import check_evidence
from infra.deploy.upload_artifacts import _assert_registry_rights
from infra.deploy.verify_artifact_receipt import verify as verify_artifact_receipt

from dynamis.config import ConfigurationError
from dynamis.deployment import DeploymentError, load_public_seed, public_rights_error
from dynamis.serving import cli
from dynamis.serving.app import create_app, serving_exposure
from dynamis.storage.object_store import immutable_object_key


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


def test_production_gate_requires_all_preview_checks(tmp_path):
    path = tmp_path / "release.json"
    sha = "a" * 40
    digest = "b" * 64
    seed = load_public_seed()[0]
    objects = [
        {
            "dataset_id": seed.dataset_id,
            "checksum_sha256": digest,
            "object_key": immutable_object_key(digest),
            "size_bytes": 1,
        }
    ]
    receipt_path = tmp_path / "preview-artifacts.json"
    receipt_path.write_text(
        json.dumps(
            {
                "environment": "preview",
                "git_sha": sha,
                "object_count": len(objects),
                "objects": objects,
            }
        ),
        encoding="utf-8",
    )
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
    digest = "b" * 64
    seed = load_public_seed()[0]
    objects = [
        {
            "dataset_id": seed.dataset_id,
            "checksum_sha256": digest,
            "object_key": immutable_object_key(digest),
            "size_bytes": 1,
        }
    ]
    receipt = {
        "environment": "preview",
        "git_sha": sha,
        "object_count": len(objects),
        "objects": objects,
    }
    path = tmp_path / "objects.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert verify_artifact_receipt(path, "preview", sha) == ()
    receipt["objects"][0]["object_key"] = "public/url"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    assert "object key is not checksum-bound" in verify_artifact_receipt(path, "preview", sha)[0]


def test_artifact_receipt_rejects_multiple_objects(tmp_path):
    sha = "a" * 40
    digest = "b" * 64
    seed = load_public_seed()[0]
    obj = {
        "dataset_id": seed.dataset_id,
        "checksum_sha256": digest,
        "object_key": immutable_object_key(digest),
        "size_bytes": 1,
    }
    path = tmp_path / "objects.json"
    path.write_text(
        json.dumps(
            {
                "environment": "preview",
                "git_sha": sha,
                "object_count": 2,
                "objects": [obj, {**obj, "checksum_sha256": "c" * 64}],
            }
        ),
        encoding="utf-8",
    )
    assert "exactly one" in verify_artifact_receipt(path, "preview", sha)[0]


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
