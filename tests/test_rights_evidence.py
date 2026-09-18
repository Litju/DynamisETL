"""The rights-evidence receipt must stay reproducible and registry-consistent.

No machine-specific state may enter the artifact; the observed license
identifier must agree with the machine-readable registry the pipeline enforces.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from dynamis.config import repository_root
from dynamis.registry import source_by_id, validate_registry

EVIDENCE_PATH = repository_root() / "sources" / "rights_evidence.json"
REQUIRED_FIELDS = {
    "dataset_id",
    "source_url",
    "doi",
    "authority_type",
    "license_identifier_observed",
    "source_revision",
    "rendered_record_discrepancy",
    "observed_at",
    "decision",
}
IDENTIFIER_TOKEN = re.compile(r"^[A-Za-z0-9.-]+")


def _document() -> dict[str, Any]:
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


def test_evidence_document_declares_the_required_fields() -> None:
    document = _document()
    assert document["schema_version"] == "1"
    entries = document["evidence"]
    assert entries
    for entry in entries:
        missing = REQUIRED_FIELDS - set(entry)
        assert not missing, (entry.get("dataset_id"), sorted(missing))
        for field in REQUIRED_FIELDS - {"doi", "rendered_record_discrepancy"}:
            assert entry[field], (entry["dataset_id"], field)
        assert entry["rendered_record_discrepancy"] is None or isinstance(
            entry["rendered_record_discrepancy"], str
        )
        date.fromisoformat(entry["observed_at"])


def test_every_evidence_dataset_exists_in_the_registry() -> None:
    registry = validate_registry()
    entries = _document()["evidence"]
    ids = [entry["dataset_id"] for entry in entries]
    assert len(ids) == len(set(ids))
    for entry in entries:
        source_by_id(registry, entry["dataset_id"])


def test_observed_identifiers_agree_with_the_registry_policy() -> None:
    registry = validate_registry()
    for entry in _document()["evidence"]:
        policy = source_by_id(registry, entry["dataset_id"]).license
        match = IDENTIFIER_TOKEN.match(entry["license_identifier_observed"])
        assert match is not None
        assert policy.identifier is not None
        assert match.group(0).lower() == policy.identifier.lower()


def test_evidence_contains_no_machine_specific_state() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")
    text = text.replace("https://", "").replace("http://", "")
    assert not re.search(r"[A-Za-z]:[\\/]", text)
    assert "\\\\" not in text
