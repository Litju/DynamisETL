"""Typed Arrow modality schemas: completeness, units, nullability, registry."""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.contracts import Modality
from dynamis.contracts.enums import MeasurementClass
from dynamis.contracts.schemas import (
    DENSE_KEY,
    MEASUREMENT_CLASSES_KEY,
    MODALITY_KEY,
    MODALITY_SCHEMAS,
    SCHEMA_VERSION,
    SCHEMA_VERSION_KEY,
    SUBJECT_REQUIRED_KEY,
    TIME_MONOTONICITY_KEY,
    UNITS_KEY,
    axis_of,
    contract_of,
    coordinate_frame_required,
    get_schema,
    get_schema_by_contract,
    is_dense,
    modality_of,
    nullable_reason_of,
    schema_fingerprint,
    si_unit_of,
    subject_required,
    time_monotonicity,
    with_file_metadata,
)
from dynamis.contracts.units import is_si_unit

EXPECTED_CONTRACTS = {
    Modality.GNSS: "gnss_sample",
    Modality.IMU: "imu_sample",
    Modality.FORCE: "force_sample",
    Modality.LPT: "lpt_sample",
    Modality.TRACKING: "tracking_sample",
    Modality.EVENT: "event_record",
    Modality.POSE: "pose_joint_sample",
}

# Concepts a modality legitimately cannot provide, and therefore may null out.
ALLOWED_NULL_RATE = {Modality.EVENT}
DENSE_MODALITIES = set(Modality) - ALLOWED_NULL_RATE
SUBJECT_REQUIRED = {Modality.GNSS, Modality.IMU, Modality.FORCE, Modality.LPT, Modality.POSE}
FRAME_REQUIRED = {Modality.IMU, Modality.FORCE, Modality.TRACKING, Modality.POSE}


def test_every_modality_has_exactly_one_schema() -> None:
    assert set(MODALITY_SCHEMAS) == set(Modality)
    for modality, schema in MODALITY_SCHEMAS.items():
        assert contract_of(schema) == EXPECTED_CONTRACTS[modality]
        assert modality_of(schema) is modality


def test_public_package_exposes_every_modality_schema() -> None:
    from dynamis.contracts import (
        EVENT_SCHEMA,
        FORCE_SCHEMA,
        GNSS_SCHEMA,
        IMU_SCHEMA,
        LPT_SCHEMA,
        POSE_SCHEMA,
        TRACKING_SCHEMA,
    )

    assert GNSS_SCHEMA is get_schema("gnss")
    assert IMU_SCHEMA is get_schema(Modality.IMU)
    assert FORCE_SCHEMA is get_schema("force")
    assert LPT_SCHEMA is get_schema("lpt")
    assert TRACKING_SCHEMA is get_schema("tracking")
    assert EVENT_SCHEMA is get_schema("event")
    assert POSE_SCHEMA is get_schema("pose")


@pytest.mark.parametrize("modality", list(Modality))
def test_identity_and_timing_envelope_is_present(modality: Modality) -> None:
    schema = get_schema(modality)
    names = set(schema.names)
    required = {
        "dataset_id",
        "session_id",
        "trial_id",
        "subject_id",
        "device_id",
        "stream_id",
        "sample_index",
        "t_rel_ns",
        "timestamp_utc_ns",
        "nominal_sampling_rate_hz",
        "measurement_class",
        "clock_id",
        "synchronization_spec_id",
        "coordinate_frame_id",
    }
    assert required <= names

    for name in ("dataset_id", "session_id", "stream_id", "clock_id", "synchronization_spec_id"):
        assert not schema.field(name).nullable
    assert not schema.field("sample_index").nullable
    assert not schema.field("t_rel_ns").nullable
    assert not schema.field("measurement_class").nullable
    assert schema.field("t_rel_ns").type == pa.int64()


@pytest.mark.parametrize("modality", list(Modality))
def test_schema_metadata_is_complete(modality: Modality) -> None:
    schema = get_schema(modality)
    metadata = schema.metadata or {}
    assert metadata[SCHEMA_VERSION_KEY] == SCHEMA_VERSION.encode()
    assert metadata[UNITS_KEY] == b"SI"
    assert metadata[MODALITY_KEY] == modality.value.encode()
    assert metadata[DENSE_KEY] == (b"true" if modality in DENSE_MODALITIES else b"false")
    assert metadata[SUBJECT_REQUIRED_KEY] == (b"true" if modality in SUBJECT_REQUIRED else b"false")
    classes = str(metadata[MEASUREMENT_CLASSES_KEY], "utf-8").split(",")
    assert classes == [member.value for member in MeasurementClass]
    assert time_monotonicity(schema) in {"strict", "non_decreasing"}
    assert TIME_MONOTONICITY_KEY in metadata


@pytest.mark.parametrize("modality", list(Modality))
def test_subject_and_frame_requirements_match_the_scientific_reality(modality: Modality) -> None:
    schema = get_schema(modality)
    assert subject_required(schema) == (modality in SUBJECT_REQUIRED)
    assert coordinate_frame_required(schema) == (modality in FRAME_REQUIRED)
    assert is_dense(schema) == (modality in DENSE_MODALITIES)


@pytest.mark.parametrize("modality", list(Modality))
def test_sampling_rate_nullability_is_honest(modality: Modality) -> None:
    field_ = get_schema(modality).field("nominal_sampling_rate_hz")
    if modality in ALLOWED_NULL_RATE:
        assert field_.nullable
        assert nullable_reason_of(field_)
    else:
        assert not field_.nullable


@pytest.mark.parametrize("modality", list(Modality))
def test_every_unit_is_si_and_every_null_is_justified(modality: Modality) -> None:
    schema = get_schema(modality)
    units_seen = 0
    for field_ in schema:
        unit = si_unit_of(field_)
        if unit is not None:
            units_seen += 1
            assert is_si_unit(unit), f"{modality.value}.{field_.name} declares {unit!r}"
        if field_.nullable:
            reason = nullable_reason_of(field_)
            assert reason, f"{modality.value}.{field_.name} is nullable without a reason"
        else:
            assert nullable_reason_of(field_) is None
    assert units_seen >= 1


def test_expected_payload_columns_exist_per_modality() -> None:
    expectations = {
        Modality.GNSS: {"latitude_deg", "longitude_deg", "speed_m_s"},
        Modality.IMU: {"accel_x_m_s2", "gyro_z_rad_s"},
        Modality.FORCE: {"force_z_n", "cop_x_m"},
        Modality.LPT: {"position_m", "velocity_m_s"},
        Modality.TRACKING: {"object_id", "x_m", "confidence"},
        Modality.EVENT: {"event_id", "event_type", "provider_player_id"},
        Modality.POSE: {"skeleton_id", "joint_id", "confidence", "error_m"},
    }
    for modality, columns in expectations.items():
        assert columns <= set(get_schema(modality).names)


def test_axis_metadata_is_attached_to_vector_components() -> None:
    force = get_schema(Modality.FORCE)
    assert axis_of(force.field("force_z_n")) == "z"
    assert axis_of(force.field("force_x_n")) == "x"
    imu = get_schema(Modality.IMU)
    assert axis_of(imu.field("gyro_y_rad_s")) == "y"


def test_get_schema_rejects_unknown_modalities() -> None:
    with pytest.raises(KeyError):
        get_schema("eav_measurement")
    with pytest.raises(KeyError):
        get_schema_by_contract("measurement")
    assert get_schema_by_contract("gnss_sample") is get_schema(Modality.GNSS)


def test_fingerprint_is_stable_and_sensitive() -> None:
    first = schema_fingerprint(get_schema(Modality.FORCE))
    second = schema_fingerprint(get_schema(Modality.FORCE))
    assert first == second

    original = get_schema(Modality.FORCE)
    relaxed = pa.schema(
        [
            field_.with_nullable(True) if field_.name == "stream_id" else field_
            for field_ in original
        ],
        metadata=original.metadata,
    )
    assert schema_fingerprint(relaxed) != first


def test_file_metadata_keeps_the_schema_contract() -> None:
    schema = with_file_metadata(
        get_schema(Modality.GNSS), nominal_sampling_rate_hz=10.0, extras={"origin": "test"}
    )
    assert schema.metadata[b"dynamis.nominal_sampling_rate_hz"] == b"10.0"
    assert schema.metadata[b"dynamis.origin"] == b"test"
    assert schema.metadata[SCHEMA_VERSION_KEY] == SCHEMA_VERSION.encode()
    assert schema.names == get_schema(Modality.GNSS).names


def test_event_records_have_no_sampling_rate_concept() -> None:
    schema = get_schema(Modality.EVENT)
    assert not is_dense(schema)
    assert schema.field("nominal_sampling_rate_hz").nullable
    assert contract_of(schema) == "event_record"
