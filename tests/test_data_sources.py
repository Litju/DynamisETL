"""DATA_SOURCES.md must stay in agreement with the machine-readable registry."""

from __future__ import annotations

import re

import pytest

from dynamis.config import repository_root
from dynamis.contracts import Modality
from dynamis.registry import validate_registry

DOC_NAME = "DATA_SOURCES.md"
REGISTRY_ROW = re.compile(r"^\|\s*`(?P<dataset_id>[a-z0-9-]+)`\s*\|")


@pytest.fixture(scope="module")
def doc_text() -> str:
    return (repository_root() / DOC_NAME).read_text(encoding="utf-8")


def _table_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = REGISTRY_ROW.match(line.strip())
        if match:
            rows[match.group("dataset_id")] = line
    return rows


def test_notice_document_exists_and_names_the_code_license(doc_text: str) -> None:
    assert "Apache-2.0" in doc_text
    assert "never committed to Git" in doc_text


def test_every_registry_source_has_exactly_one_notice_row(doc_text: str) -> None:
    rows = _table_rows(doc_text)
    registry = validate_registry()
    registry_ids = {source.dataset_id for source in registry.sources}
    assert set(rows) == registry_ids
    assert len(rows) == len(registry_ids)


def test_license_identifiers_in_the_document_match_the_registry(doc_text: str) -> None:
    rows = _table_rows(doc_text)
    registry = validate_registry()
    for source in registry.sources:
        row = rows[source.dataset_id]
        if source.license.identifier is None:
            assert "unclear" in row.lower(), source.dataset_id
        else:
            assert source.license.identifier in row, source.dataset_id


def test_per_source_sections_exist_for_every_dataset(doc_text: str) -> None:
    registry = validate_registry()
    for source in registry.sources:
        assert f"### `{source.dataset_id}`" in doc_text


def test_document_states_the_local_only_boundary(doc_text: str) -> None:
    assert doc_text.lower().count("local") >= 3
    section = doc_text.split("### `tackle-workload`", 1)[1].split("###", 1)[0].lower()
    assert "no explicit license value" in section
    assert "local" in section


def test_document_records_the_res104_white_and_gymaware_rights_decisions(doc_text: str) -> None:
    registry = validate_registry()
    for dataset_id in ("white-cmj-acc-grf", "gymaware-landmine-vision"):
        section = doc_text.split(f"### `{dataset_id}`", 1)[1].split("###", 1)[0]
        assert registry.source(dataset_id).license.identifier == "CC-BY-4.0"
        assert "CC BY 4.0" in section.replace("CC-BY-4.0", "CC BY 4.0")
        assert "rights_evidence.json" in section


def _normalized_section(doc_text: str, dataset_id: str) -> str:
    section = doc_text.split(f"### `{dataset_id}`", 1)[1].split("###", 1)[0]
    return " ".join(section.replace("*", "").split()).lower()


def test_document_preserves_the_openbiomechanics_exclusion(doc_text: str) -> None:
    section = doc_text.split("### `openbiomechanics`", 1)[1].split("##", 1)[0].lower()
    assert "professional sports organization" in section
    assert "financial analysis" in section
    assert "optional and license-gated" in section


def test_document_separates_the_gymaware_archive_and_paper_populations(doc_text: str) -> None:
    section = _normalized_section(doc_text, "gymaware-landmine-vision")
    for token in (
        "24 male athletes",
        "247 valid method-comparison trials",
        "254 GymAware set exports",
        "653 GymAware rep rows",
        "275 numbered rows",
        "51 display-name identities",
        "52 pseudonymous/unresolved subject identities",
        "653 canonical rep trials",
        "source set `059`",
        "not the paper's 247",
        "not the paper's 24",
    ):
        assert token.lower() in section, token


def test_document_excludes_soccermon_and_states_the_frame_neutrality(doc_text: str) -> None:
    assert "SoccerMon is NOT a V1 dependency" in doc_text
    assert "soccermon" in doc_text.lower()


def test_document_mentions_every_modality_scope() -> None:
    # Sanity check that the notice lists the sources covering all seven modalities.
    registry = validate_registry()
    covered: set[Modality] = set()
    for source in registry.sources:
        covered.update(source.modalities)
    assert covered == set(Modality)


def test_document_does_not_contain_machine_specific_paths(doc_text: str) -> None:
    assert not re.search(
        r"[A-Z]:[\\/](?![\\/])", doc_text.replace("http://", "").replace("https://", "")
    )
