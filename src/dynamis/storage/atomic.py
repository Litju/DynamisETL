"""Atomic file writes.

Every generated scientific artifact is written to a temporary sibling file and
moved into place with :func:`os.replace`, so a crashed or interrupted run can
never leave a partially written artifact that later readers would trust.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4


def atomic_write_bytes(path: Path, data: bytes) -> Path:
    """Write ``data`` to ``path`` atomically. Returns the final path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return target


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_path(path: Path):
    """Context manager yielding a temporary path that is replaced on success.

    On any exception the temporary file is removed and the target is untouched,
    which keeps Bronze/Silver/Gold free of half-written artifacts.
    """
    return _AtomicPathWriter(Path(path))


class _AtomicPathWriter:
    def __init__(self, target: Path) -> None:
        self._target = target
        self._tmp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")

    def __enter__(self) -> Path:
        self._target.parent.mkdir(parents=True, exist_ok=True)
        return self._tmp

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            os.replace(self._tmp, self._target)
        elif self._tmp.exists():
            self._tmp.unlink(missing_ok=True)


def sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
