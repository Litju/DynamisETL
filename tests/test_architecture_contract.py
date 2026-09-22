from pathlib import Path

from scripts.validate_architecture import validate_files


def test_frozen_architecture_contract_is_valid() -> None:
    validate_files(Path(__file__).resolve().parents[1])
