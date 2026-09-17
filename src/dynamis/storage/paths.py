"""Deterministic Bronze/Silver/Gold/quarantine path conventions.

Layout under the external scientific-data root (never inside the repository)::

    <dataset_root>/
      bronze/<dataset_id>/<version>/<upstream key...>        immutable native files
      bronze/_manifests/<dataset_id>/<version>.json         retrieval manifest + checksums
      silver/dataset_id=<id>/modality=<modality>/session_id=<sid>/<stream>.parquet
      gold/<dataset_id>/<mart>/<name>.parquet
      quarantine/dataset_id=<id>/rule=<rule>/<name>.parquet
      cache/<namespace>/
      tmp/<run_id>/

Partition keys are explicit and hive-style so DuckDB can prune on them without
extra catalog state. Writes go through :mod:`dynamis.storage.parquet`, which is
atomic and records checksums.
"""

from __future__ import annotations

import re
from pathlib import Path

from dynamis.config import Settings
from dynamis.contracts import ArtifactLayer, Modality

PARTITION_KEYS = ("dataset_id", "modality", "session_id")

_UNSAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class PathConventionError(ValueError):
    """Raised for unsafe or non-conforming path components."""


def sanitize_component(value: str, *, field: str = "component") -> str:
    """Make a single path component safe and deterministic.

    Rejects empty values, path separators, ``..`` and drive prefixes; replaces
    any remaining unsafe character with ``_``.
    """
    if not value or not value.strip():
        raise PathConventionError(f"{field} must be a non-empty string")
    candidate = value.strip()
    if candidate in {".", ".."}:
        raise PathConventionError(f"{field}={value!r} is not a safe path component")
    if "/" in candidate or "\\" in candidate:
        raise PathConventionError(f"{field}={value!r} must not contain path separators")
    if re.match(r"^[A-Za-z]:", candidate):
        raise PathConventionError(f"{field}={value!r} must not be a drive-qualified path")
    cleaned = _UNSAFE_COMPONENT.sub("_", candidate)
    if not _ALLOWED_COMPONENT.match(cleaned):
        raise PathConventionError(f"{field}={value!r} cannot be sanitized safely")
    return cleaned


def safe_upstream_key(key: str) -> Path:
    """Validate an upstream archive key and convert it to a relative path.

    Mirrors zip-slip defence: absolute paths, drive prefixes, UNC prefixes and
    ``..`` traversal are refused rather than rewritten.
    """
    normalized = key.replace("\\", "/").strip()
    if not normalized:
        raise PathConventionError("upstream key must be non-empty")
    if normalized.startswith("/") or normalized.startswith("//"):
        raise PathConventionError(f"upstream key {key!r} must be relative")
    if re.match(r"^[A-Za-z]:", normalized):
        raise PathConventionError(f"upstream key {key!r} must not be drive-qualified")
    parts = normalized.split("/")
    for part in parts:
        if part in {"..", "", "."}:
            raise PathConventionError(
                f"upstream key {key!r} has an empty, current or parent directory segment"
            )
    relative = Path(*parts)
    if relative.is_absolute():  # pragma: no cover - defensive
        raise PathConventionError(f"upstream key {key!r} must be relative")
    return relative


def layer_dir(settings: Settings, layer: ArtifactLayer) -> Path:
    return settings.dataset_root / layer.value


def ensure_dataset_layout(settings: Settings) -> tuple[Path, ...]:
    """Create the six canonical dataset layers. Idempotent."""
    created: list[Path] = []
    for layer in ArtifactLayer:
        target = layer_dir(settings, layer)
        target.mkdir(parents=True, exist_ok=True)
        created.append(target)
    manifests = bronze_manifest_dir(settings)
    manifests.mkdir(parents=True, exist_ok=True)
    created.append(manifests)
    return tuple(created)


def ensure_database_layout(settings: Settings) -> tuple[Path, ...]:
    """Create the PostgreSQL state directory and the DuckDB parent directory."""
    from dynamis.config import postgres_subdir

    created: list[Path] = []
    for target in (postgres_subdir(settings.database_root), settings.duckdb_path.parent):
        target.mkdir(parents=True, exist_ok=True)
        created.append(target)
    return tuple(created)


def bronze_manifest_dir(settings: Settings) -> Path:
    """Directory holding immutable retrieval manifests (bronze metadata)."""
    return layer_dir(settings, ArtifactLayer.BRONZE) / "_manifests"


def bronze_native_path(
    settings: Settings,
    *,
    dataset_id: str,
    version: str,
    key: str,
) -> Path:
    root = (
        layer_dir(settings, ArtifactLayer.BRONZE)
        / sanitize_component(dataset_id, field="dataset_id")
        / sanitize_component(version, field="version")
    )
    return root / safe_upstream_key(key)


def bronze_manifest_path(settings: Settings, *, dataset_id: str, version: str) -> Path:
    return (
        bronze_manifest_dir(settings)
        / sanitize_component(dataset_id, field="dataset_id")
        / f"{sanitize_component(version, field='version')}.json"
    )


def partition_dir(
    settings: Settings,
    layer: ArtifactLayer,
    *,
    dataset_id: str,
    modality: Modality | str | None = None,
    session_id: str | None = None,
    rule: str | None = None,
) -> Path:
    """Hive-style partition directory for silver/gold/quarantine artifacts."""
    parts = [layer_dir(settings, layer), f"dataset_id={sanitize_component(dataset_id)}"]
    if modality is not None:
        value = modality.value if isinstance(modality, Modality) else modality
        parts.append(f"modality={sanitize_component(value, field='modality')}")
    if session_id is not None:
        parts.append(f"session_id={sanitize_component(session_id, field='session_id')}")
    if rule is not None:
        parts.append(f"rule={sanitize_component(rule, field='rule')}")
    return Path(*parts)


def silver_parquet_path(
    settings: Settings,
    *,
    dataset_id: str,
    modality: Modality | str,
    session_id: str,
    stream_id: str,
) -> Path:
    directory = partition_dir(
        settings,
        ArtifactLayer.SILVER,
        dataset_id=dataset_id,
        modality=modality,
        session_id=session_id,
    )
    return directory / f"{sanitize_component(stream_id, field='stream_id')}.parquet"


def gold_parquet_path(
    settings: Settings,
    *,
    dataset_id: str,
    mart: str,
    name: str,
) -> Path:
    directory = (
        layer_dir(settings, ArtifactLayer.GOLD)
        / sanitize_component(dataset_id, field="dataset_id")
        / sanitize_component(mart, field="mart")
    )
    return directory / f"{sanitize_component(name, field='name')}.parquet"


def quarantine_parquet_path(
    settings: Settings,
    *,
    dataset_id: str,
    rule: str,
    name: str,
) -> Path:
    directory = partition_dir(
        settings,
        ArtifactLayer.QUARANTINE,
        dataset_id=dataset_id,
        rule=rule,
    )
    return directory / f"{sanitize_component(name, field='name')}.parquet"


def cache_dir(settings: Settings, namespace: str) -> Path:
    return layer_dir(settings, ArtifactLayer.CACHE) / sanitize_component(
        namespace, field="namespace"
    )


def receipt_path(
    settings: Settings,
    *,
    dataset_id: str,
    kind: str,
    name: str,
) -> Path:
    """Deterministic JSON receipt under the cache layer's ``receipts`` namespace.

    Receipts (acquisition, discovery, reconciliation) are provenance evidence
    regenerated by deterministic runs; they live outside Bronze/Silver/Gold so
    they can never be mistaken for immutable scientific artifacts.
    """
    return (
        cache_dir(settings, "receipts")
        / sanitize_component(dataset_id, field="dataset_id")
        / sanitize_component(kind, field="kind")
        / f"{sanitize_component(name, field='name')}.json"
    )


def tmp_run_dir(settings: Settings, run_id: str) -> Path:
    return layer_dir(settings, ArtifactLayer.TMP) / sanitize_component(run_id, field="run_id")


def relative_posix(root: Path, path: Path) -> str:
    """Repository/root-relative POSIX path used in provenance records."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PathConventionError(
            f"{path} is not located under the configured root {root}"
        ) from exc


def partition_values(
    dataset_id: str,
    *,
    modality: Modality | str,
    session_id: str,
) -> dict[str, str]:
    value = modality.value if isinstance(modality, Modality) else modality
    return {"dataset_id": dataset_id, "modality": value, "session_id": session_id}
