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


def validate_files(root: Path) -> None:
    schema_path = root / "architecture" / "system-v2.schema.json"
    contract_path = root / "architecture" / "system-v2.json"
    schema = _load(schema_path)
    contract = _load(contract_path)
    _validate(contract, schema, schema, "$")
    _check_project_invariants(root, contract)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_files(args.root.resolve())
    print(
        f"architecture contract PASSED: {args.root.resolve() / 'architecture' / 'system-v2.json'}"
    )


if __name__ == "__main__":
    main()
