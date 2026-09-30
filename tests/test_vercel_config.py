from __future__ import annotations

import json
from pathlib import Path


def test_vercel_services_keep_api_public_before_spa_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "vercel.json").read_text(encoding="utf-8"))

    assert config["git"]["deploymentEnabled"] == {"main": False}
    assert set(config["services"]) == {"app", "web"}
    assert config["services"]["app"]["root"] == "."
    assert config["services"]["app"]["framework"] == "fastapi"
    assert config["services"]["app"]["entrypoint"] == "api.index:app"
    assert config["services"]["web"]["root"] == "apps/web"
    assert config["services"]["web"]["framework"] == "vite"
    assert all("bindings" not in service for service in config["services"].values())

    rewrites = config["rewrites"]
    assert [rewrite["source"] for rewrite in rewrites] == [
        "/api",
        "/api/(.*)",
        "/(.*)",
    ]
    assert [rewrite["destination"]["service"] for rewrite in rewrites] == [
        "app",
        "app",
        "web",
    ]
