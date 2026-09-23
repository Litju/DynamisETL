"""Read-only tactical authority loaders for typed serving."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from dynamis.config import repository_root
from dynamis.serving.models import (
    TacticalCapabilityLevels,
    TacticalCapabilityView,
    TacticalMethodologyPage,
    TacticalMetricMethodologyView,
    TacticalQualityView,
)

CAPABILITY_PATH = Path("sources") / "tactical-capability-matrix.json"
METRICS_PATH = Path("architecture") / "tactical-metrics.json"
ALGORITHMS = {
    "A": "tactical.team_geometry",
    "B": "tactical.spatial_territory",
    "C": "tactical.arrival_time",
    "D": "tactical.source_event_snapshot",
    "E": "tactical.team_shape",
    "V3": "tactical.matchlab_shape",
}


@lru_cache(maxsize=1)
def _authority() -> tuple[dict[str, Any], dict[str, Any]]:
    root = repository_root()
    return (
        json.loads((root / CAPABILITY_PATH).read_text(encoding="utf-8")),
        json.loads((root / METRICS_PATH).read_text(encoding="utf-8")),
    )


def _levels(payload: dict[str, Any]) -> TacticalCapabilityLevels:
    return TacticalCapabilityLevels(**payload["capabilities"])


def tactical_capability(dataset_id: str) -> TacticalCapabilityView | None:
    capabilities, _metrics = _authority()
    payload = capabilities["datasets"].get(dataset_id)
    if payload is None:
        return None
    return TacticalCapabilityView(
        dataset_id=dataset_id,
        accepted_slice=payload["accepted_slice"],
        semantics=payload["semantics"],
        capabilities=_levels(payload),
        quality_evidence=payload["quality_evidence"],
        unavailable_reasons=payload["unavailable_reasons"],
    )


def tactical_methodology() -> TacticalMethodologyPage:
    _capabilities, metrics = _authority()
    return TacticalMethodologyPage(
        authority=metrics["authority"],
        metrics=[
            TacticalMetricMethodologyView(
                metric_id=item["id"],
                level=item["level"],
                name=item["name"],
                unit=item["unit"],
                kind=item["kind"],
                definition=item["definition"],
                measurement_class=(
                    metrics["matchlab_tactical_v3"]["measurement_class"]
                    if item["level"] == "V3"
                    else metrics["levels"][item["level"]]["measurement_class"]
                ),
                algorithm_id=ALGORITHMS[item["level"]],
                algorithm_version=(
                    metrics.get("level_c_model", {}).get("version")
                    if item["level"] == "C"
                    else metrics["matchlab_tactical_v3"]["algorithm_version"]
                    if item["level"] == "V3"
                    else "1"
                ),
            )
            for item in metrics["metrics"]
        ],
    )


def tactical_quality(dataset_id: str) -> TacticalQualityView | None:
    capability = tactical_capability(dataset_id)
    if capability is None:
        return None
    classes = capability.semantics.get("measurement_classes", {})
    return TacticalQualityView(
        dataset_id=dataset_id,
        capabilities=capability.capabilities,
        quality_evidence=capability.quality_evidence,
        measurement_classes={str(key): str(value) for key, value in classes.items()},
        unavailable_reasons=capability.unavailable_reasons,
        disclosure=(
            "PIPELINE_DERIVED is deterministic output from canonical inputs; "
            "MODEL_ESTIMATED is a versioned assumption-bearing model. Unsupported "
            "capabilities are unavailable rather than zero-filled."
        ),
    )


__all__ = ["tactical_capability", "tactical_methodology", "tactical_quality"]
