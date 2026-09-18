"""The processor framework must be deterministic, versioned and provenance-bound."""

from __future__ import annotations

import json

import pyarrow as pa
import pytest

from dynamis.config import Settings
from dynamis.contracts import AlgorithmKind, MeasurementClass
from dynamis.processors import (
    MetricDeclaration,
    ProcessorInput,
    ProcessorResult,
    ProcessorSpec,
    ScalarMetric,
    SeriesOutput,
    canonical_parameters,
    code_git_sha,
    derived_metric_id,
    deterministic_run_id,
    execute_processor,
    parameters_hash,
)
from dynamis.storage.atomic import sha256_file


def _spec(parameters: dict | None = None) -> ProcessorSpec:
    return ProcessorSpec(
        algorithm_id="test.deterministic",
        name="Deterministic test processor",
        version="1.2.3",
        description="Framework test fixture.",
        parameters={} if parameters is None else parameters,
    )


def _result(spec: ProcessorSpec, *, value: float = 1.5) -> ProcessorResult:
    table = pa.table(
        {
            "sample_index": pa.array([0, 1, 2], type=pa.int64()),
            "t_rel_ns": pa.array([0, 1_000_000_000, 2_000_000_000], type=pa.int64()),
            "value_m_s": pa.array([0.0, 1.0, 2.0], type=pa.float64()),
        }
    )
    return ProcessorResult(
        spec=spec,
        metrics=(
            ScalarMetric(
                declaration=MetricDeclaration(
                    metric_id="test.scalar",
                    name="Test scalar",
                    si_unit="m",
                    description="Framework test scalar.",
                ),
                value=value,
                session_id="s1",
                stream_id="stream-1",
                provenance={"input_rows": 3},
            ),
        ),
        series=(SeriesOutput(name="derived", table=table),),
    )


def _input(settings: Settings) -> ProcessorInput:
    path = settings.dataset_root / "silver" / "input.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"canonical-input")
    return ProcessorInput(
        role="silver",
        path=path,
        relative_path="silver/input.parquet",
        checksum_sha256=sha256_file(path),
        row_count=3,
    )


def test_parameters_hash_is_order_independent_and_value_sensitive() -> None:
    first = {"beta": [1.0, 2.0], "alpha": {"nested": True}}
    second = {"alpha": {"nested": True}, "beta": [1.0, 2.0]}
    assert canonical_parameters(first) == canonical_parameters(second)
    assert parameters_hash(first) == parameters_hash(second)
    assert parameters_hash(first) != parameters_hash({**first, "beta": [1.0, 2.5]})
    with pytest.raises(ValueError, match="canonical JSON"):
        parameters_hash({"bad": float("nan")})


def test_processor_spec_projects_a_processor_algorithm_contract() -> None:
    spec = _spec({"window_s": 5.0})
    contract = spec.contract(code_sha="a" * 40)
    assert contract.kind is AlgorithmKind.PROCESSOR
    assert contract.parameters_hash == spec.parameters_hash
    assert contract.code_git_sha == "a" * 40


def test_scalar_metric_rejects_non_finite_values() -> None:
    declaration = MetricDeclaration(
        metric_id="test.scalar", name="Test", si_unit="m", description="d"
    )
    with pytest.raises(ValueError, match="must be finite"):
        ScalarMetric(declaration=declaration, value=float("nan"))


def test_derived_and_run_identities_are_content_addressed() -> None:
    spec = _spec({"window_s": 5.0})
    common = {
        "dataset_id": "white-cmj-acc-grf",
        "metric_id": "test.scalar",
        "algorithm_id": spec.algorithm_id,
        "parameters_hash": spec.parameters_hash,
        "session_id": "s1",
        "stream_id": "stream-1",
    }
    base = derived_metric_id(**common)
    assert base == derived_metric_id(**common)
    assert base != derived_metric_id(**{**common, "parameters_hash": "0" * 64})
    assert base != derived_metric_id(**{**common, "stream_id": "stream-2"})

    run_common = {
        "dataset_id": "white-cmj-acc-grf",
        "algorithm_id": spec.algorithm_id,
        "version": spec.version,
        "parameters_hash": spec.parameters_hash,
        "input_checksums": ("a" * 64,),
    }
    run_id = deterministic_run_id(**run_common)
    assert run_id == deterministic_run_id(**run_common)
    assert run_id != deterministic_run_id(**{**run_common, "code_sha": "b" * 40})
    assert run_id != deterministic_run_id(**{**run_common, "input_checksums": ("c" * 64,)})


def test_execute_processor_materializes_deterministic_series_and_receipt(
    tmp_settings: Settings,
) -> None:
    spec = _spec({"window_s": 5.0})
    processor_input = _input(tmp_settings)
    first = execute_processor(
        tmp_settings,
        result=_result(spec),
        dataset_id="white-cmj-acc-grf",
        inputs=(processor_input,),
        series_key="stream-1",
        persist=False,
    )
    second = execute_processor(
        tmp_settings,
        result=_result(spec),
        dataset_id="white-cmj-acc-grf",
        inputs=(processor_input,),
        series_key="stream-1",
        persist=False,
    )
    assert first.run_id == second.run_id
    assert first.series[0].artifact.checksum_sha256 == second.series[0].artifact.checksum_sha256
    assert first.series[0].artifact.relative_path == second.series[0].artifact.relative_path
    assert first.input_checksums == (processor_input.checksum_sha256,)

    receipt = json.loads(
        (tmp_settings.dataset_root / str(first.receipt_path)).read_text(encoding="utf-8")
    )
    assert receipt["run_id"] == first.run_id
    assert receipt["parameters_hash"] == spec.parameters_hash
    assert receipt["metrics"][0]["measurement_class"] == MeasurementClass.PIPELINE_DERIVED.value
    assert receipt["metrics"][0]["value"] == 1.5
    assert receipt["inputs"][0]["checksum_sha256"] == processor_input.checksum_sha256
    assert receipt["series"][0]["checksum_sha256"] == first.series[0].artifact.checksum_sha256


def test_execute_processor_requires_inputs_and_series_key(tmp_settings: Settings) -> None:
    spec = _spec()
    with pytest.raises(ValueError, match="at least one input"):
        execute_processor(
            tmp_settings,
            result=_result(spec),
            dataset_id="white-cmj-acc-grf",
            inputs=(),
            series_key="stream-1",
            persist=False,
        )
    with pytest.raises(ValueError, match="deterministic series key"):
        execute_processor(
            tmp_settings,
            result=_result(spec),
            dataset_id="white-cmj-acc-grf",
            inputs=(_input(tmp_settings),),
            series_key=" ",
            persist=False,
        )


def test_code_git_sha_env_override_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DYNAMIS_CODE_GIT_SHA", "c" * 40)
    assert code_git_sha() == "c" * 40
    monkeypatch.setenv("DYNAMIS_CODE_GIT_SHA", "not-a-sha")
    with pytest.raises(ValueError, match="40-character Git SHA"):
        code_git_sha()
