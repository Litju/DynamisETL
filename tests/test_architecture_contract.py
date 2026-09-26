from pathlib import Path

from scripts.validate_architecture import validate_files


def test_frozen_architecture_contract_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    validate_files(root)
    v4_docs = root / "docs" / "architecture" / "v4"
    for document in (
        "ARCHITECTURE.md", "SPORTS-SEMANTICS.md", "DATA-GRAIN.md", "SOURCE-CATALOG.md",
        "CAPABILITY-PROFILE.md", "PRODUCT-ROUTING.md", "SPATIAL-REFERENCE.md",
        "CLOCK-AUTHORITY.md", "STORAGE-PARTITIONING.md", "MIGRATION.md",
        "ADR-001-sports-semantic-overlay.md", "ADR-002-source-catalog.md",
        "ADR-003-parquet-no-table-format.md", "ADR-004-cross-sport-event-envelope.md",
        "ADR-005-capability-product-routing.md",
    ):
        assert (v4_docs / document).is_file(), document
