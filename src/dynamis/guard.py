"""Repository boundary guard.

Rejects, in the working tree and therefore in any future commit:

* scientific data files (dataset payloads must never enter the repository);
* database engine state (DuckDB/PostgreSQL files);
* secrets (``.env``, keys, credentials embedded in source);
* machine-specific absolute paths hard-coded in application modules;
* broad static-analysis suppression in ``src``.

Standard library only. This module must not import third-party packages, so CI
can run it on a clean checkout before any dependency installation. That is why
:func:`repository_root` is defined locally rather than imported from
:mod:`dynamis.config`.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".ruff_cache",
        ".pytest_cache",
        ".mypy_cache",
        ".pyright",
        "htmlcov",
        ".hypothesis",
    }
)

FORBIDDEN_SUFFIXES = frozenset(
    {
        ".parquet",
        ".arrow",
        ".ipc",
        ".feather",
        ".duckdb",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".c3d",
        ".npz",
        ".npy",
        ".xlsx",
        ".xls",
        ".zip",
        ".tar",
        ".tgz",
        ".h5",
        ".hdf5",
        ".bag",
        ".mcap",
    }
)

FORBIDDEN_NAMES = frozenset({".env", "pgpass", ".pgpass", "id_rsa", "id_ed25519"})
FORBIDDEN_SUFFIX_NAMES = (".pem", ".key", ".pfx", ".p12")

ALLOWED_ENV_EXAMPLES = frozenset({".env.example"})

APPLICATION_SOURCE_ROOT = Path("src")
# Drive-qualified absolute path: an uppercase drive letter, a colon, then a
# separator. The uppercase requirement distinguishes a real Windows root from
# the lowercase regex/string escapes that appear constantly in source
# ("type:\s", "path:\n"). The lookahead excludes URL forms ("https://") and the
# escaped-backslash path form, which is covered separately below.
DRIVE_ABSOLUTE_PATH = re.compile(r"[A-Z]:[\\/](?![\\/])")
# The escaped-backslash form, where the source text encodes a doubled separator
# after the drive letter (the way a Windows path appears inside a Python literal).
DRIVE_ESCAPED_PATH = re.compile(r"[A-Z]:\\\\[A-Za-z0-9_.\\-]+")
CREDENTIAL_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^@\s/]+@")
SUPPRESSION = re.compile(r"(#\s*type:\s*ignore|#\s*pyright:\s*ignore)")

TEXT_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})
CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".ini", ".cfg", ".toml", ".json", ".sql"})
# ``.env.example`` exists precisely to document placeholder credentials.
CREDENTIAL_EXEMPT_NAMES = frozenset({".env.example"})


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        yield path


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def git_ignored(root: Path, relative: str) -> bool:
    """True when git reports the path as ignored.

    Local, git-ignored state (``.env``, ``.venv``, caches) legitimately exists on
    a developer machine and must not fail the guard; in CI the same paths are
    simply absent. Non-git environments are treated as "not ignored".
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--quiet", "--", relative],
            capture_output=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - no git available
        return False
    return result.returncode == 0


def scan(root: Path) -> tuple[str, ...]:
    """Return every boundary violation found under ``root``."""
    problems: list[str] = []
    resolved_root = Path(root).resolve()

    for path in iter_files(resolved_root):
        relative = _relative(resolved_root, path)
        name = path.name
        suffix = path.suffix.lower()

        candidate = (
            suffix in FORBIDDEN_SUFFIXES
            or name in FORBIDDEN_NAMES
            or name.endswith(FORBIDDEN_SUFFIX_NAMES)
            or (name.startswith(".env") and name not in ALLOWED_ENV_EXAMPLES)
        )
        if candidate and git_ignored(resolved_root, relative):
            continue

        if suffix in FORBIDDEN_SUFFIXES:
            problems.append(f"forbidden data artifact: {relative}")
        if name in FORBIDDEN_NAMES:
            problems.append(f"forbidden secret/config file: {relative}")
        if name.endswith(FORBIDDEN_SUFFIX_NAMES):
            problems.append(f"forbidden key material: {relative}")
        if name.startswith(".env") and name not in ALLOWED_ENV_EXAMPLES:
            problems.append(f"forbidden environment file: {relative}")

        if suffix in TEXT_SOURCE_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover - defensive
                problems.append(f"unreadable source file {relative}: {exc}")
                continue
            if relative.startswith(APPLICATION_SOURCE_ROOT.as_posix()):
                for number, line in enumerate(text.splitlines(), start=1):
                    if DRIVE_ABSOLUTE_PATH.search(line) or DRIVE_ESCAPED_PATH.search(line):
                        problems.append(
                            f"machine-specific absolute path in application source: "
                            f"{relative}:{number}"
                        )
                    if SUPPRESSION.search(line):
                        problems.append(
                            f"static-analysis suppression in application source: "
                            f"{relative}:{number}"
                        )
            if _contains_credential(relative, text):
                problems.append(f"embedded credential in source: {relative}")

    for required in (Path(".gitignore"), Path(".gitattributes"), Path("LICENSE")):
        if not (resolved_root / required).is_file():
            problems.append(f"missing required repository file: {required.as_posix()}")

    gitignore = resolved_root / ".gitignore"
    if gitignore.is_file() and ".env" not in gitignore.read_text(encoding="utf-8"):
        problems.append(".gitignore does not ignore .env")

    return tuple(problems)


def _contains_credential(relative: str, text: str) -> bool:
    name = Path(relative).name
    if name in CREDENTIAL_EXEMPT_NAMES:
        return False
    if Path(relative).suffix.lower() not in TEXT_SOURCE_SUFFIXES | CONFIG_SUFFIXES:
        return False
    return bool(CREDENTIAL_URL.search(text))


def repository_root() -> Path:
    """Repository root derived from this module's location (never hard-coded)."""
    return Path(__file__).resolve().parents[2]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dynamis-guard",
        description=(
            "Reject scientific data, database state, secrets, machine-specific paths and "
            "static-analysis suppression from the repository."
        ),
    )
    parser.add_argument("--root", type=Path, default=None, help="Repository root")
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else repository_root()
    problems = scan(root)
    if problems:
        print(f"repository boundary FAILED ({len(problems)} problem(s)):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("repository boundary PASSED")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via console script
    raise SystemExit(main())
