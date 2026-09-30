"""Record Preview evidence only after database, artifact, and browser gates pass."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from infra.deploy.seed import _database_target, _sha
from infra.deploy.verify_artifact_receipt import verify as verify_artifact_receipt

from dynamis.config import ENV_POSTGRES_URL, resolved_environ
from dynamis.deployment import DeploymentError
from dynamis.storage.atomic import atomic_write_text


def record(preview_url: str, artifact_receipt: Path, smoke_receipt: Path, output: Path) -> Path:
    values = resolved_environ()
    if values.get("DYNAMIS_DEPLOY_ENV") != "preview":
        raise DeploymentError("DYNAMIS_DEPLOY_ENV must be preview when recording Preview evidence")
    if values.get("VERCEL_ENV") and values["VERCEL_ENV"] != "preview":
        raise DeploymentError("DYNAMIS_DEPLOY_ENV does not match the Vercel environment")

    parsed_url = urlparse(preview_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise DeploymentError("preview URL must be an HTTPS origin")
    if parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise DeploymentError("Preview evidence cannot use a local URL")
    preview_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

    sha = _sha()
    failures = verify_artifact_receipt(artifact_receipt, "preview", sha)
    if failures:
        raise DeploymentError("Preview artifact receipt failed: " + "; ".join(failures))

    smoke: dict[str, object] = json.loads(smoke_receipt.read_text(encoding="utf-8"))
    if (
        smoke.get("environment") != "preview"
        or smoke.get("git_sha") != sha
        or smoke.get("preview_url") != preview_url
    ):
        raise DeploymentError("browser smoke receipt does not match this Preview revision and URL")
    smoke_gates = smoke.get("gates")
    if not isinstance(smoke_gates, dict) or any(
        smoke_gates.get(name) != "passed"
        for name in ("rights", "secrets", "private_blob", "deep_links", "external_smoke")
    ):
        raise DeploymentError("browser smoke receipt is incomplete")

    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [
            sys.executable,
            str(root / "infra/deploy/check_migrations.py"),
            "--require-gold",
        ],
        cwd=root,
        check=True,
    )
    database_url = values.get(ENV_POSTGRES_URL, "").strip()
    if not database_url:
        raise DeploymentError(f"{ENV_POSTGRES_URL} is required for Preview evidence")

    output = output.resolve()
    try:
        relative_receipt = artifact_receipt.resolve().relative_to(output.parent)
    except ValueError:
        relative_receipt = Path(os.path.relpath(artifact_receipt.resolve(), output.parent))
    evidence = {
        "environment": "preview",
        "git_sha": sha,
        "preview_url": preview_url,
        "database_target_sha256": _database_target(database_url),
        "artifact_receipt": relative_receipt.as_posix(),
        "gates": {
            "rights": "passed",
            "secrets": "passed",
            "migration": "passed",
            "object_reconciliation": "passed",
            "external_smoke": "passed",
        },
    }
    atomic_write_text(output, json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview-url", required=True)
    parser.add_argument("--artifact-receipt", type=Path, required=True)
    parser.add_argument("--smoke-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    sha = _sha()
    root = Path(__file__).resolve().parents[2]
    output = args.output or root / "output" / "deploy" / f"preview-release-{sha}.json"
    try:
        path = record(args.preview_url, args.artifact_receipt, args.smoke_receipt, output)
    except (DeploymentError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Preview release evidence blocked: {exc}", file=sys.stderr)
        return 2
    print(f"Preview release evidence: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
