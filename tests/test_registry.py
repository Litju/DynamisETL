"""Dataset registry: rights audit, corrections and CLI behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dynamis.contracts import (
    DatasetRegistry,
    DatasetSource,
    LicensePolicy,
    LicenseStatus,
    Modality,
    RedistributionPolicy,
)
from dynamis.registry import (
    REGISTRY_SCHEMA_VERSION,
    RegistryError,
    audit_registry,
    default_registry_path,
    describe_registry,
    load_registry,
    main,
    source_by_id,
    validate_registry,
)

EXPECTED_SOURCE_COUNT = 8
UNCLEAR_RIGHTS = {
    "white-cmj-acc-grf",
    "gymaware-landmine-vision",
    "tackle-workload",
}


def test_registry_loads_and_passes_the_rights_audit() -> None:
    registry = validate_registry()
    assert registry.schema_version == REGISTRY_SCHEMA_VERSION
    assert len(registry.sources) == EXPECTED_SOURCE_COUNT
    assert audit_registry(registry) == ()


def test_registry_covers_every_v1_modality() -> None:
    registry = validate_registry()
    covered: set[Modality] = set()
    for source in registry.sources:
        covered.update(source.modalities)
    assert covered == set(Modality)


def test_unclear_rights_sources_stay_local_only() -> None:
    registry = validate_registry()
    for dataset_id in UNCLEAR_RIGHTS:
        policy = source_by_id(registry, dataset_id).license
        assert policy.identifier is None
        assert policy.local_only
        assert policy.redistribution.value == "prohibited"
    local_only = {source.dataset_id for source in registry.sources if source.license.local_only}
    assert local_only == UNCLEAR_RIGHTS


def test_spl_license_excludes_the_openbiomechanics_exclusion() -> None:
    registry = validate_registry()
    spl = source_by_id(registry, "spl-open-data")
    assert spl.license.identifier == "CC-BY-NC-SA-4.0"
    assert spl.license.noncommercial_only
    assert spl.license.share_alike
    text = " ".join(spl.license.restrictions).lower()
    assert "share-alike" in text
    assert "professional sports organization" not in text
    assert "financial analysis" not in text


def test_openbiomechanics_keeps_its_additional_exclusion() -> None:
    registry = validate_registry()
    obp = source_by_id(registry, "openbiomechanics")
    assert obp.license.identifier == "CC-BY-NC-SA-4.0"
    assert obp.license.noncommercial_only and obp.license.share_alike
    text = " ".join(obp.license.restrictions).lower()
    assert "professional sports organization" in text
    assert "financial analysis" in text
    assert obp.versions[-1].optional


def test_no_dataset_is_fetched_in_res96() -> None:
    registry = validate_registry()
    for source in registry.sources:
        for version in source.versions:
            assert version.retrieval.status.value == "not_fetched"
            assert version.retrieval.retrieved_at is None
            for item in version.retrieval.files:
                assert item.local_sha256 is None
                assert item.retrieved_at is None


def test_registry_records_retrieval_and_license_metadata() -> None:
    registry = validate_registry()
    for source in registry.sources:
        assert source.adapter_id
        assert source.upstream_urls
        assert source.v1_role and source.initial_scope
        for version in source.versions:
            assert str(version.upstream_url)
            assert version.retrieval.files


def test_dfl_doi_points_at_the_dataset_not_only_the_paper() -> None:
    registry = validate_registry()
    dfl = source_by_id(registry, "dfl-sportec-idsse")
    assert dfl.doi == "10.6084/m9.figshare.28196177"
    assert any("pysport/idsse-data" in str(url) for url in dfl.upstream_urls)


def test_audit_detects_a_tampered_spl_policy() -> None:
    registry = validate_registry()
    spl = source_by_id(registry, "spl-open-data")
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
            "Professional sports organization employees are forbidden any use.",
        ),
    )
    tampered = DatasetSource.model_copy(spl, update={"license": tampered_policy})
    problems = audit_registry(DatasetRegistry.model_copy(registry, update={"sources": (tampered,)}))
    assert any("must not be attached to SPL" in problem for problem in problems)


def test_audit_detects_missing_openbiomechanics_exclusion() -> None:
    registry = validate_registry()
    obp = source_by_id(registry, "openbiomechanics")
    tampered_policy = LicensePolicy(
        identifier="CC-BY-NC-SA-4.0",
        status=obp.license.status,
        attribution_required=True,
        noncommercial_only=True,
        share_alike=True,
        redistribution=obp.license.redistribution,
        local_only=False,
        restrictions=("Non-commercial use only.",),
    )
    tampered = DatasetSource.model_copy(obp, update={"license": tampered_policy})
    problems = audit_registry(DatasetRegistry.model_copy(registry, update={"sources": (tampered,)}))
    assert any("exclusion must be preserved" in problem for problem in problems)


def test_audit_rejects_prohibited_redistribution_that_is_not_local_only() -> None:
    registry = validate_registry()
    white = source_by_id(registry, "white-cmj-acc-grf")
    # Contract-legal (a declared licence with prohibited redistribution is allowed),
    # but the audit must still reject it: prohibited means local-only.
    inconsistent = LicensePolicy(
        identifier="CC-BY-NC-4.0",
        status=LicenseStatus.DECLARED,
        attribution_required=True,
        noncommercial_only=True,
        share_alike=False,
        redistribution=RedistributionPolicy.PROHIBITED,
        local_only=False,
        restrictions=("Non-commercial use only.",),
    )
    with pytest.raises(ValidationError):
        LicensePolicy(
            identifier=None,
            status=LicenseStatus.UNCLEAR,
            attribution_required=True,
            noncommercial_only=False,
            share_alike=False,
            redistribution=RedistributionPolicy.PROHIBITED,
            local_only=False,
            restrictions=(),
        )
    tampered = DatasetSource.model_copy(white, update={"license": inconsistent})
    problems = audit_registry(DatasetRegistry.model_copy(registry, update={"sources": (tampered,)}))
    assert any("not marked local-only" in problem for problem in problems)


def test_registry_rejects_duplicate_dataset_ids() -> None:
    registry = validate_registry()
    with pytest.raises(ValidationError):
        DatasetRegistry(sources=(*registry.sources, registry.sources[0]))


def test_lookup_helpers_raise_for_unknown_ids() -> None:
    registry = validate_registry()
    source = source_by_id(registry, "skillcorner-opendata")
    assert source.version("4340d274572876239c154c90bc507a9b3250a656")
    with pytest.raises(KeyError):
        source.version("does-not-exist")
    with pytest.raises(KeyError):
        source_by_id(registry, "does-not-exist")


def test_describe_registry_reports_complete_modality_coverage() -> None:
    summary = describe_registry(validate_registry())
    assert "modality coverage: complete" in summary
    assert "sources=8" in summary


def test_registry_schema_version_is_enforced(tmp_path: Path) -> None:
    payload = json.loads(default_registry_path().read_text(encoding="utf-8"))
    payload["schema_version"] = "999"
    target = tmp_path / "registry.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RegistryError, match="schema_version"):
        load_registry(target)


def test_registry_loader_reports_invalid_json(tmp_path: Path) -> None:
    target = tmp_path / "registry.json"
    target.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RegistryError, match="not valid JSON"):
        load_registry(target)


def test_cli_passes_on_the_canonical_registry(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--quiet"]) == 0
    assert "PASSED" in capsys.readouterr().out


def test_cli_fails_on_a_rights_violation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.loads(default_registry_path().read_text(encoding="utf-8"))
    for source in payload["sources"]:
        if source["dataset_id"] == "spl-open-data":
            source["license"]["identifier"] = "MIT"
            source["license"]["restrictions"] = ["Non-commercial use only.", "Share-alike."]
    target = tmp_path / "registry.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["--registry", str(target), "--quiet"]) == 1
    captured = capsys.readouterr()
    assert "FAILED" in captured.err
