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
COMMIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
#: An immutable GitHub reference: /blob/<sha>/, /raw/<sha>/, /tree/<sha>/ or
#: /commit/<sha> instead of a mutable branch or repository-root URL.
PINNED_COMPANION_URL = re.compile(
    r"/(?:blob|raw|tree)/(?P<revision>[0-9a-f]{40})/|/commit/(?P<commit_revision>[0-9a-f]{40})$"
)
WHITE_COMPANION_REVISION = "5c0c8b8278b78d1cb1ab2cf931e05693c2f84334"
WHITE_COMPANION_URL = (
    f"https://github.com/markgewhite/acc2grf-cmj/blob/{WHITE_COMPANION_REVISION}/README.md"
)


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


def test_companion_repository_evidence_is_pinned_to_an_immutable_revision() -> None:
    """Companion-repository rights evidence must stay reproducible.

    A repository-root or branch URL can change after the audit. Every entry that
    cites companion repository evidence must record the exact commit SHA and a
    URL that embeds that same revision.
    """
    entries = _document()["evidence"]
    assert any(entry.get("companion_evidence_url") for entry in entries)
    for entry in entries:
        url = entry.get("companion_evidence_url")
        revision = entry.get("companion_evidence_revision")
        if url is None:
            assert revision is None, entry["dataset_id"]
            continue
        assert revision is not None, entry["dataset_id"]
        assert COMMIT_REVISION.fullmatch(revision), (entry["dataset_id"], revision)
        match = PINNED_COMPANION_URL.search(url)
        assert match is not None, (entry["dataset_id"], url)
        pinned_revision = match.group("revision") or match.group("commit_revision")
        assert pinned_revision == revision, (entry["dataset_id"], url)


def test_white_companion_readme_evidence_is_commit_pinned() -> None:
    entry = next(
        item for item in _document()["evidence"] if item["dataset_id"] == "white-cmj-acc-grf"
    )
    assert entry["companion_evidence_revision"] == WHITE_COMPANION_REVISION
    assert entry["companion_evidence_url"] == WHITE_COMPANION_URL
    assert WHITE_COMPANION_REVISION in entry["companion_evidence"]


def test_evidence_contains_no_machine_specific_state() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")
    text = text.replace("https://", "").replace("http://", "")
    assert not re.search(r"[A-Za-z]:[\\/]", text)
    assert "\\\\" not in text
