"""Reject production rollout unless every preview release gate passed."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_GATES = (
    "rights",
    "secrets",
    "migration",
    "object_reconciliation",
    "external_smoke",
)


def check_evidence(path: Path, git_sha: str) -> tuple[str, ...]:
    try:
        evidence: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ("release evidence is missing or invalid JSON",)
    failures: list[str] = []
    if evidence.get("environment") != "preview":
        failures.append("evidence must describe the preview environment")
    if evidence.get("git_sha") != git_sha:
        failures.append("preview Git SHA does not match the release revision")
    preview_url = evidence.get("preview_url")
    if not isinstance(preview_url, str) or not preview_url.startswith("https://"):
        failures.append("preview URL is missing")
    target_hash = evidence.get("database_target_sha256")
    if not isinstance(target_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", target_hash):
        failures.append("preview Neon target fingerprint is missing")
    receipt_value = evidence.get("artifact_receipt")
    if not isinstance(receipt_value, str) or not receipt_value:
        failures.append("preview artifact receipt is missing")
    else:
        receipt_path = Path(receipt_value)
        if not receipt_path.is_absolute():
            receipt_path = path.resolve().parent / receipt_path
        from infra.deploy.verify_artifact_receipt import verify

        failures.extend(verify(receipt_path, "preview", git_sha))
    gates = evidence.get("gates")
    if not isinstance(gates, dict):
        return tuple([*failures, "gate results are missing"])
    failures.extend(name for name in REQUIRED_GATES if gates.get(name) != "passed")
    return tuple(failures)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--git-sha", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.git_sha):
        parser.error("--git-sha must be a 40-character lowercase Git SHA")
    failures = check_evidence(args.evidence, args.git_sha)
    if failures:
        print("production promotion blocked: " + "; ".join(failures), file=sys.stderr)
        return 2
    print("preview rights, secrets, migrations, object reconciliation, and external smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
