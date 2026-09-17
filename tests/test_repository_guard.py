"""Repository boundary: no data, no secrets, no hard-coded machine paths."""

from __future__ import annotations

from pathlib import Path

from dynamis.config import repository_root
from dynamis.guard import scan


def test_repository_tree_has_no_boundary_violations() -> None:
    problems = scan(repository_root())
    assert problems == ()


def test_guard_flags_a_data_artifact(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("X", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (tmp_path / "leak.parquet").write_bytes(b"PAR1")

    problems = scan(tmp_path)
    assert any("forbidden data artifact" in item for item in problems)


def test_guard_flags_a_committed_env_file(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("X", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")

    problems = scan(tmp_path)
    assert any("forbidden environment file" in item for item in problems)


def test_guard_flags_machine_paths_and_suppressions_in_src(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("X", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    source = tmp_path / "src" / "bad.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'ROOT = "E:/Data/Datasets/DynamisETL"\nx = compute()  # type: ignore[arg-type]\n',
        encoding="utf-8",
    )

    problems = scan(tmp_path)
    assert any("machine-specific absolute path" in item for item in problems)
    assert any("static-analysis suppression" in item for item in problems)


def test_guard_flags_an_embedded_credential(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("X", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "settings.py").write_text(
        'URL = "postgresql://' + "dynamis:supersecret@db:5432/dynamis" + '"\n',
        encoding="utf-8",
    )

    problems = scan(tmp_path)
    assert any("embedded credential" in item for item in problems)


def test_guard_requires_the_foundation_files(tmp_path: Path) -> None:
    problems = scan(tmp_path)
    assert any("missing required repository file: .gitignore" in item for item in problems)
    assert any("missing required repository file: LICENSE" in item for item in problems)


def test_guard_accepts_urls_and_escapes_in_source(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("X", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    source = tmp_path / "src" / "good.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'URL = "https://zenodo.org/records/10913119"\n'
        'PATTERN = r"[A-Z]:[\\\\/]"\n'
        'MESSAGE = "audit failed:\\n{err}"\n',
        encoding="utf-8",
    )

    assert scan(tmp_path) == ()


def test_all_exported_contract_names_exist() -> None:
    import dynamis.contracts as contracts

    missing = [name for name in contracts.__all__ if not hasattr(contracts, name)]
    assert missing == []


def test_alembic_configuration_has_no_committed_credential() -> None:
    ini = (repository_root() / "alembic.ini").read_text(encoding="utf-8")
    for line in ini.splitlines():
        if line.startswith("sqlalchemy.url"):
            assert "://" in line
            assert "@" not in line.split("://", 1)[1].split("/", 1)[0]


def test_env_example_is_committed_and_env_is_not() -> None:
    root = repository_root()
    assert (root / ".env.example").is_file()
    assert ".env" in (root / ".gitignore").read_text(encoding="utf-8")


def test_no_real_dataset_directory_is_present_in_the_repository() -> None:
    root = repository_root()
    for name in ("bronze", "silver", "gold", "quarantine", "datasets", "databases"):
        candidate = root / name
        assert not candidate.exists(), f"{name} must not exist inside the repository"
