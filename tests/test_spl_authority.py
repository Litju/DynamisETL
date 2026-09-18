"""SPL Open Data rights authority and the fail-closed acquisition gate.

SPL's own LICENSE at the pinned revision carries a role-dependent exclusion on
top of CC BY-NC-SA 4.0. The registry must preserve it, and acquisition must
refuse to proceed until the operator explicitly acknowledges it.
"""

from __future__ import annotations

import json

import pytest

from dynamis.config import repository_root
from dynamis.contracts import DatasetRegistry, DatasetSource, LicensePolicy
from dynamis.registry import (
    SPL_DATASET_ID,
    SPL_EXCLUSION_MARKERS,
    SPL_LICENSE_ACKNOWLEDGEMENT,
    AcknowledgementRequired,
    assert_acquisition_acknowledged,
    audit_registry,
    required_acknowledgements,
    source_by_id,
    validate_registry,
)

DOC_NAME = "DATA_SOURCES.md"


def test_spl_license_preserves_its_role_dependent_exclusion() -> None:
    """SPL's own LICENSE at the pinned revision carries the exclusion."""
    registry = validate_registry()
    spl = source_by_id(registry, SPL_DATASET_ID)
    assert spl.license.identifier == "CC-BY-NC-SA-4.0"
    assert spl.license.noncommercial_only
    assert spl.license.share_alike
    text = " ".join(spl.license.restrictions).lower()
    assert "share-alike" in text
    assert "a3f9cffbde917b1e1747cedd6ec25dfab18c6051" in text
    for marker in SPL_EXCLUSION_MARKERS:
        assert marker in text
    assert "employee" in text and "contractor" in text
    assert "paid" in text


def test_audit_detects_a_tampered_spl_policy() -> None:
    registry = validate_registry()
    spl = source_by_id(registry, SPL_DATASET_ID)
    tampered_policy = LicensePolicy(
        identifier="CC-BY-NC-SA-4.0",
        status=spl.license.status,
        attribution_required=True,
        noncommercial_only=True,
        share_alike=True,
        redistribution=spl.license.redistribution,
        local_only=False,
        restrictions=(
            "Non-commercial use only.",
            "Share-alike applies to data derivatives.",
        ),
    )
    tampered = DatasetSource.model_copy(spl, update={"license": tampered_policy})
    problems = audit_registry(DatasetRegistry.model_copy(registry, update={"sources": (tampered,)}))
    assert any("role-dependent exclusion" in problem for problem in problems)
    assert any("financial analysis" in problem for problem in problems)


def test_audit_detects_a_gated_source_without_recorded_restrictions() -> None:
    registry = validate_registry()
    spl = source_by_id(registry, SPL_DATASET_ID)
    tampered_policy = LicensePolicy(
        identifier="CC-BY-NC-SA-4.0",
        status=spl.license.status,
        attribution_required=True,
        noncommercial_only=True,
        share_alike=True,
        redistribution=spl.license.redistribution,
        local_only=False,
        restrictions=(),
    )
    tampered = DatasetSource.model_copy(spl, update={"license": tampered_policy})
    problems = audit_registry(DatasetRegistry.model_copy(registry, update={"sources": (tampered,)}))
    assert any("acknowledgement gate exists" in problem for problem in problems)


def test_spl_acknowledgement_gate_is_source_specific_and_fails_closed() -> None:
    registry = validate_registry()
    spl = source_by_id(registry, SPL_DATASET_ID)
    assert required_acknowledgements(SPL_DATASET_ID) == (SPL_LICENSE_ACKNOWLEDGEMENT,)
    with pytest.raises(AcknowledgementRequired, match="fail-closed"):
        assert_acquisition_acknowledged(spl, ())
    with pytest.raises(AcknowledgementRequired):
        assert_acquisition_acknowledged(spl, ("some-unrelated-acknowledgement",))
    assert_acquisition_acknowledged(spl, (SPL_LICENSE_ACKNOWLEDGEMENT,))

    # A source without a gate is not blocked by unrelated acknowledgements.
    assert_acquisition_acknowledged(source_by_id(registry, "dfl-sportec-idsse"), ())
    assert required_acknowledgements("dfl-sportec-idsse") == ()


def test_rights_evidence_records_spl_exclusion_and_the_fail_closed_gate() -> None:
    document = json.loads(
        (repository_root() / "sources" / "rights_evidence.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in document["evidence"] if item["dataset_id"] == SPL_DATASET_ID)
    registry = validate_registry()
    text = " ".join(source_by_id(registry, SPL_DATASET_ID).license.restrictions).lower()
    for marker in SPL_EXCLUSION_MARKERS:
        assert marker in text
        assert marker in entry["decision"].lower()
    assert required_acknowledgements(SPL_DATASET_ID)
    assert "acknowledge" in entry["decision"].lower()


def test_document_preserves_the_spl_role_dependent_exclusion() -> None:
    doc_text = (repository_root() / DOC_NAME).read_text(encoding="utf-8")
    section = doc_text.split("### `spl-open-data`", 1)[1].split("###", 1)[0]
    section = " ".join(section.replace("*", "").split()).lower()
    assert "professional sports organization" in section
    assert "financial analysis" in section
    assert "significant shareholder" in section
    assert "a3f9cffbde917b1e1747cedd6ec25dfab18c6051" in section
    assert "--acknowledge-spl-license-restrictions" in section
