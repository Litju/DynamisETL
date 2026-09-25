"""Validate the frozen V2 architecture contract without third-party packages."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """Raised when the machine-readable architecture contract is invalid."""


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _validate(value: Any, schema: dict[str, Any], root_schema: dict[str, Any], path: str) -> None:
    reference = schema.get("$ref")
    if reference:
        if not reference.startswith("#/$defs/"):
            raise ContractError(f"unsupported schema reference at {path}: {reference}")
        name = reference.removeprefix("#/$defs/")
        _validate(value, root_schema["$defs"][name], root_schema, path)
        return
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, item) for item in types):
            raise ContractError(f"{path}: expected {types}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: {value!r} is not in {schema['enum']!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ContractError(f"{path}: string is shorter than minLength")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            raise ContractError(f"{path}: {value!r} does not match {pattern!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value <= schema.get("exclusiveMinimum", float("-inf")):
            raise ContractError(f"{path}: number must be greater than exclusiveMinimum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ContractError(f"{path}: array has fewer than minItems")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate(item, item_schema, root_schema, f"{path}[{index}]")
    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise ContractError(f"{path}: missing required properties {missing}")
        if len(value) < schema.get("minProperties", 0):
            raise ContractError(f"{path}: object has fewer than minProperties")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise ContractError(f"{path}: unknown properties {unknown}")
        for name, child_schema in properties.items():
            if name in value:
                _validate(value[name], child_schema, root_schema, f"{path}.{name}")
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            for name, child in value.items():
                if name not in properties:
                    _validate(child, additional, root_schema, f"{path}.{name}")


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc


def _check_project_invariants(root: Path, contract: dict[str, Any]) -> None:
    modules = contract["modules"]
    ids = [module["id"] for module in modules]
    if len(ids) != len(set(ids)):
        raise ContractError("modules: ids must be unique")
    required_modules = {
        "product-shell",
        "durable-context",
        "server-cache",
        "transient-analysis-state",
        "general-analytics",
        "dense-signal",
        "field-replay",
        "pose-replay",
        "browser-dense-plane",
        "control-api",
        "dense-read-plane",
        "scientific-compute",
        "artifact-plane",
        "postgres-control-plane",
        "runtime-readiness",
    }
    if set(ids) != required_modules:
        raise ContractError(
            f"modules: expected exactly {sorted(required_modules)}, got {sorted(ids)}"
        )
    by_id = {module["id"]: module for module in modules}
    if "uPlot" not in by_id["dense-signal"]["benchmark_selected_implementation"]:
        raise ContractError("dense-signal must select the measured uPlot implementation")
    if "ECharts" not in by_id["general-analytics"]["benchmark_selected_implementation"]:
        raise ContractError("general-analytics must retain ECharts")
    if "Instanced" not in by_id["pose-replay"]["benchmark_selected_implementation"]:
        raise ContractError("pose-replay must select the measured instanced/batched hot path")
    if "WebGL2" not in next(
        item["selection"] for item in contract["decisions"] if item["id"] == "webgpu-default"
    ):
        raise ContractError("webgpu-default must freeze WebGL2")
    dense_read = by_id["dense-read-plane"]["benchmark_selected_implementation"]
    if "PyArrow" not in dense_read or "DuckDB" not in dense_read:
        raise ContractError("dense-read-plane must record both measured query owners")
    if contract["deployment"]["frontend"] != "Vercel-hosted React/Vite workbench only":
        raise ContractError("frontend deployment authority drifted")
    if (
        contract["deployment"]["api"]
        != "Cloud Run FastAPI container with PyArrow/DuckDB dense reads"
    ):
        raise ContractError("API deployment authority drifted")
    if "private" not in contract["deployment"]["object_store"].lower():
        raise ContractError("object storage must remain private")

    forbidden_patterns = {
        "src": re.compile(
            r"(?:^|\s)(?:import|from)\s+(?:polars|pandas|datafusion|pyo3|rust)(?:\s|$|\.)",
            re.MULTILINE,
        ),
        "web": re.compile(
            r"(?:from|import)\s+[\"'](?:redux|mobx|@duckdb|duckdb-wasm)[\"']", re.MULTILINE
        ),
    }
    for path in (root / "src").rglob("*.py"):
        if forbidden_patterns["src"].search(path.read_text(encoding="utf-8")):
            raise ContractError(f"forbidden architecture dependency in {path}")
    for path_root in (root / "apps" / "web" / "src",):
        for path in (*path_root.rglob("*.ts"), *path_root.rglob("*.tsx")):
            if forbidden_patterns["web"].search(path.read_text(encoding="utf-8")):
                raise ContractError(f"forbidden architecture dependency in {path}")


def _check_matchlab_v3_invariants(contract: dict[str, Any]) -> None:
    if contract["contract_id"] != "dynamisdata-matchlab-rendering":
        raise ContractError("V3 contract must be scoped to MatchLab rendering")
    if "outside this boundary" not in contract["scope"]:
        raise ContractError("V3 must leave V2 contracts outside MatchLab intact")
    technology = contract["technology"]
    if technology["canvas_count"] != 1 or technology["initial_backend"] != "WebGL2":
        raise ContractError("MatchLab requires one Canvas and WebGL2 as its initial backend")
    if "Drei View" not in technology["multi_view"]:
        raise ContractError("MatchLab multi-view must use Drei View")
    if "no duplicate store" not in contract["state_ownership"]["context_role"]:
        raise ContractError("MatchFrameContext must not become a second state store")

    context = contract["match_frame_context"]
    if "BigInt" not in context["canonical_time"]:
        raise ContractError("MatchFrameContext canonical time must remain BigInt-safe")
    if "latest real Pose sample at or before" not in context["pose_resolution"]:
        raise ContractError("Pose frames must resolve independently under their source-rate contract")
    if "1.5 nominal sample intervals" not in context["tracking_resolution"] or "1.5 nominal sample intervals" not in context["pose_resolution"]:
        raise ContractError("V3 source-frame age tolerance must remain explicit")
    if "Never interpolate" not in context["pose_resolution"]:
        raise ContractError("MatchFrameContext must not fabricate Pose samples")
    selection = contract["interaction"]["selection_authority"]
    if "Field-origin player picks commit the player and current canonical time" not in selection:
        raise ContractError("Field-origin selection must preserve canonical time")
    if "retain RES-109 section 12" not in selection:
        raise ContractError("Pose-origin selection must preserve the RES-109 subject transition")
    if "coordinates and proximity never establish identity" not in context["player_identity"]:
        raise ContractError("player identity must come from a registered identity mapping")
    if "structured" not in contract["pitch"]["geometry_source"]:
        raise ContractError("Pitch3D dimensions must come from structured source metadata")
    if "never infer" not in contract["pitch"]["missing_geometry"]:
        raise ContractError("missing metric pitch geometry must fail closed")

    presentation = contract["field_presentation"]
    if "Tactical Map" not in presentation["default_mode"] or "OrthographicCamera" not in presentation["default_mode"]:
        raise ContractError("Tactical Map must be the fitted orthographic Field default")
    if "Structure Lift" not in presentation["structure_lift"] or "orthographic" not in presentation["structure_lift"]:
        raise ContractError("Structure Lift must preserve metric pitch XY with orthographic projection")
    if "optional" not in presentation["optional_exploration"].lower():
        raise ContractError("Perspective exploration must remain optional")
    if "render-layer-depths.ts" not in presentation["depth_offset_authority"]:
        raise ContractError("Field presentation offsets must have one depth authority")
    if "one restrained DirectionalLight" not in presentation["shadow_policy"]:
        raise ContractError("analytical Field shadows must use one restrained light")
    required_planar = {"tracking positions", "functional units and inter-line gaps", "shape graph", "local triangles", "opposition relations", "hull and Voronoi", "event paths"}
    if set(presentation["planar_quantities"]) != required_planar:
        raise ContractError("tracking and ordinary tactical geometry must remain planar")

    layer_ids = [layer["id"] for layer in contract["layers"]]
    expected_layers = {
        "PitchLayer",
        "TrackingLayer",
        "TacticalLayer",
        "PoseLayer",
        "ContextLayer",
    }
    if len(layer_ids) != len(set(layer_ids)) or set(layer_ids) != expected_layers:
        raise ContractError(f"V3 layers must be exactly {sorted(expected_layers)}")

    alignment = {item["mode"]: item for item in contract["source_alignment"]}
    expected_modes = {
        "source_native",
        "tracking_anchored_display",
        "display_grounded_vertical",
    }
    if set(alignment) != expected_modes:
        raise ContractError(f"V3 source alignment modes must be exactly {sorted(expected_modes)}")
    if any(
        alignment[mode]["scientific_input_eligible"]
        for mode in expected_modes - {"source_native"}
    ):
        raise ContractError("display-transformed coordinates must never be scientific inputs")

    worker = contract["worker_data_plane"]
    for required in ("Arrow JS", "Web Worker", "Comlink"):
        if required not in worker["transport"]:
            raise ContractError(f"worker data plane must use {required}")
    if "object maps at animation-frame cadence" not in worker["rule"]:
        raise ContractError("worker contract must prohibit frame-cadence row-object maps")
    if "processors compute values" not in contract["scalar_fields"]["metric_authority"]:
        raise ContractError("scalar-field shaders must not compute scientific values")
    if "NOT PHYSICAL HEIGHT" not in contract["scalar_fields"]["elevation"]:
        raise ContractError("analytical elevation must be labeled as non-physical")

    step_ids = [step["id"] for step in contract["migration"]["steps"]]
    if step_ids != list(range(1, 14)):
        raise ContractError("V3 migration gates must be the ordered 1–13 execution contract")
    stop_rule = contract["migration"]["stop_rule"]
    if "RES-111" not in stop_rule or "RES-114" not in stop_rule:
        raise ContractError("RES-111 and RES-114 must remain gated on RES-113 acceptance")
    if set(contract["adr_ids"]) != {
        "ADR-001-renderer-migration",
        "ADR-002-shared-canvas-multiview",
        "ADR-003-worker-data-plane",
        "ADR-004-webgpu-benchmark-gate",
    }:
        raise ContractError("V3 must freeze renderer, multi-view, worker and WebGPU ADRs")


def validate_files(root: Path) -> None:
    for version in ("v2", "v3"):
        schema_path = root / "architecture" / f"system-{version}.schema.json"
        contract_path = root / "architecture" / f"system-{version}.json"
        schema = _load(schema_path)
        contract = _load(contract_path)
        _validate(contract, schema, schema, "$")
        if version == "v2":
            _check_project_invariants(root, contract)
        else:
            _check_matchlab_v3_invariants(contract)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_files(args.root.resolve())
    print(
        f"architecture contracts PASSED: V2 and MatchLab V3 in "
        f"{args.root.resolve() / 'architecture'}"
    )


if __name__ == "__main__":
    main()
