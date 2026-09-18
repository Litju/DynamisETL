"""Safe structural access to external ZIP archives.

The archive is never extracted wholesale. The central directory is inspected
first; unsafe paths (absolute, UNC-like, drive-qualified, traversal, duplicate
or case-conflicting normalized names), symlink members, excessive member counts
and unreasonable decompression expansion are rejected before any byte is read.
Selected structured members are then read through bounded streaming, and their
SHA-256 is computed from the decoded bytes so the adapter's evidence is pinned
to the immutable Bronze archive.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_MAX_MEMBERS = 10_000
DEFAULT_MAX_TOTAL_UNCOMPRESSED = 4 << 30
DEFAULT_MAX_MEMBER_BYTES = 256 << 20
DEFAULT_MAX_EXPANSION_RATIO = 200.0
DEFAULT_MAX_RATIO_FLOOR_BYTES = 1 << 20

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_SYMLINK_MODE = 0o120000


class ZipSecurityError(ValueError):
    """The archive or a member violates the external-data safety contract."""


@dataclass(frozen=True, slots=True)
class ZipMember:
    """One central-directory entry, with its safety-relevant facts."""

    name: str
    normalized_name: str
    is_dir: bool
    compressed_size: int
    uncompressed_size: int
    compress_type: int
    crc32: int
    is_symlink: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "normalized_name": self.normalized_name,
            "is_dir": self.is_dir,
            "compressed_size": self.compressed_size,
            "uncompressed_size": self.uncompressed_size,
            "compress_type": self.compress_type,
            "crc32": f"{self.crc32:08x}",
            "is_symlink": self.is_symlink,
        }


@dataclass(frozen=True, slots=True)
class ZipInspection:
    """Structural receipt of one archive's central directory."""

    archive_name: str
    archive_size: int
    members: tuple[ZipMember, ...]
    extension_counts: dict[str, int]
    extension_bytes: dict[str, int]
    root_entries: tuple[str, ...]
    compression_methods: dict[str, int]
    total_uncompressed: int
    total_compressed: int

    @property
    def file_members(self) -> tuple[ZipMember, ...]:
        return tuple(member for member in self.members if not member.is_dir)

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive": {
                "name": self.archive_name,
                "size_bytes": self.archive_size,
                "member_count": len(self.members),
                "file_member_count": len(self.file_members),
                "directory_count": len(self.members) - len(self.file_members),
                "total_uncompressed": self.total_uncompressed,
                "total_compressed": self.total_compressed,
                "compression_methods": self.compression_methods,
                "extension_counts": self.extension_counts,
                "extension_bytes": self.extension_bytes,
                "root_entries": list(self.root_entries),
            },
            "members": [member.to_dict() for member in self.members],
        }


def normalize_member_name(name: str) -> str:
    """Forward-slash, traversal-free normalization used for safety checks."""
    return posixpath.normpath(name.replace("\\", "/"))


def _member_problems(name: str, normalized: str) -> list[str]:
    problems: list[str] = []
    if name.startswith("/") or name.startswith("\\"):
        problems.append("absolute member path")
    if name.startswith("//") or name.startswith("\\\\"):
        problems.append("UNC-like member path")
    if _DRIVE_PREFIX.match(name):
        problems.append("drive-qualified member path")
    parts = name.replace("\\", "/").split("/")
    if ".." in parts:
        problems.append("parent-directory traversal")
    if normalized.startswith(".."):
        problems.append("normalized path escapes the archive root")
    if normalized.startswith("/"):
        problems.append("normalized absolute path")
    return problems


def inspect_zip(
    path: Path | str,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_total_uncompressed: int = DEFAULT_MAX_TOTAL_UNCOMPRESSED,
    max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
    ratio_floor_bytes: int = DEFAULT_MAX_RATIO_FLOOR_BYTES,
) -> ZipInspection:
    """Inspect a ZIP central directory and reject unsafe containers."""
    import zipfile

    archive_path = Path(path)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > max_members:
            raise ZipSecurityError(
                f"{archive_path.name}: {len(infos)} members exceeds the {max_members} bound"
            )
        problems: list[str] = []
        members: list[ZipMember] = []
        normalized_seen: dict[str, str] = {}
        for info in infos:
            name = info.filename
            normalized = normalize_member_name(name)
            problems.extend(f"{name}: {problem}" for problem in _member_problems(name, normalized))
            is_dir = info.is_dir() or name.endswith("/")
            is_symlink = (
                bool(info.external_attr >> 16)
                and (info.external_attr >> 16) & 0o170000 == _SYMLINK_MODE
            )
            if is_symlink:
                problems.append(f"{name}: symlink member")
            key = normalized.casefold()
            existing = normalized_seen.get(key)
            if existing is not None and existing != normalized:
                problems.append(
                    f"{name}: normalized path conflicts (case-insensitively) with {existing}"
                )
            elif existing is not None:
                problems.append(f"{name}: duplicate normalized member path")
            else:
                normalized_seen[key] = normalized
            if not is_dir and info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > max_expansion_ratio and info.file_size > ratio_floor_bytes:
                    problems.append(
                        f"{name}: expansion ratio {ratio:.1f} exceeds {max_expansion_ratio}"
                    )
            members.append(
                ZipMember(
                    name=name,
                    normalized_name=normalized,
                    is_dir=is_dir,
                    compressed_size=int(info.compress_size),
                    uncompressed_size=int(info.file_size),
                    compress_type=int(info.compress_type),
                    crc32=int(info.CRC),
                    is_symlink=is_symlink,
                )
            )
        total_uncompressed = sum(member.uncompressed_size for member in members)
        if total_uncompressed > max_total_uncompressed:
            problems.append(
                f"total uncompressed size {total_uncompressed} exceeds {max_total_uncompressed}"
            )
        if problems:
            raise ZipSecurityError(
                f"{archive_path.name}: unsafe archive members:\n  - " + "\n  - ".join(problems[:20])
            )
        extensions: Counter[str] = Counter()
        extension_bytes: Counter[str] = Counter()
        for member in members:
            if member.is_dir:
                continue
            suffix = PurePosixPath(member.normalized_name).suffix.lower() or "<none>"
            extensions[suffix] += 1
            extension_bytes[suffix] += member.uncompressed_size
        roots = sorted({member.normalized_name.split("/")[0] for member in members})
        methods = Counter(
            "stored" if member.compress_type == 0 else f"method-{member.compress_type}"
            for member in members
            if not member.is_dir
        )
        return ZipInspection(
            archive_name=archive_path.name,
            archive_size=archive_path.stat().st_size,
            members=tuple(members),
            extension_counts=dict(extensions),
            extension_bytes=dict(extension_bytes),
            root_entries=tuple(roots),
            compression_methods=dict(methods),
            total_uncompressed=total_uncompressed,
            total_compressed=sum(member.compressed_size for member in members),
        )


def read_member_bytes(
    archive_path: Path | str,
    member: str,
    *,
    max_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
) -> bytes:
    """Stream one selected member with a hard decoded-size bound."""
    import zipfile

    with zipfile.ZipFile(Path(archive_path)) as archive:
        try:
            info = archive.getinfo(member)
        except KeyError as exc:
            raise ZipSecurityError(f"{member!r} is not a member of the archive") from exc
        if info.is_dir():
            raise ZipSecurityError(f"{member!r} is a directory, not a file member")
        if info.file_size > max_bytes:
            raise ZipSecurityError(
                f"{member!r}: uncompressed size {info.file_size} exceeds the {max_bytes} bound"
            )
        chunks: list[bytes] = []
        written = 0
        with archive.open(info) as stream:
            while chunk := stream.read(1 << 20):
                written += len(chunk)
                if written > max_bytes:
                    raise ZipSecurityError(
                        f"{member!r}: decoded bytes exceed the {max_bytes} bound"
                    )
                chunks.append(chunk)
        return b"".join(chunks)


def sha256_member(archive_path: Path | str, member: str) -> str:
    """SHA-256 of one member's decoded bytes (the adapter's pinned evidence)."""
    return hashlib.sha256(read_member_bytes(archive_path, member)).hexdigest()


def structured_members(
    inspection: ZipInspection,
    *,
    suffixes: tuple[str, ...] = (".csv", ".xlsx"),
) -> tuple[ZipMember, ...]:
    """File members whose extension makes them structured measurement sources."""
    return tuple(
        member
        for member in inspection.file_members
        if PurePosixPath(member.normalized_name).suffix.lower() in suffixes
    )
