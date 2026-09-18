"""Typed Arrow modality schemas: completeness, units, nullability, registry."""

from __future__ import annotations

import pyarrow as pa
import pytest

from dynamis.contracts import Modality
from dynamis.contracts.enums import MeasurementClass
from dynamis.contracts.schemas import (
    CONTRACT_SCHEMA_VERSIONS,
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
    schema_version_of,
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
    expected_version = CONTRACT_SCHEMA_VERSIONS.get(contract_of(schema), SCHEMA_VERSION)
    assert metadata[SCHEMA_VERSION_KEY] == expected_version.encode()
    assert schema_version_of(schema) == expected_version
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
        Modality.POSE: {"skeleton_id", "joint_id", "is_available", "confidence", "error_m"},
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


# Pinned at RES-103 (commit a165728) before the RES-98 additive contract work.
# A mismatch means an unrelated modality's schema identity silently changed and
# every already-materialized Silver artifact for that modality is invalidated.
# Pose was deliberately re-versioned by RES-99 (landmark-set topology and
# explicit joint availability), so it carries its own pinned identity below.
RES103_FINGERPRINTS = {
    Modality.GNSS: "9e6888ce09fc901219cd8876e65e2909822d8f7d40aa7820732f264b437e86bc",
    Modality.LPT: "2ca7c89cbfd39b734e2a0bd96a8015f381df41307328400946955264651980b2",
    Modality.TRACKING: "00670b561c77866de51abe70e705081538c2da8bc877df429b8d5eae39653d90",
    Modality.EVENT: "4ce5b3ddc4f976586b0b918dd859f05d5b6c797bde18acf5daa61f329e252048",
}

#: Pose contract revision 2, pinned the moment RES-99 sealed it.
POSE_V2_FINGERPRINT = "c9406ad450940e6ca546f7d05e1b13a656cfb2f7339089b33f76cdc31798a880"


@pytest.mark.parametrize("modality", list(RES103_FINGERPRINTS))
def test_untouched_modality_schemas_keep_their_res103_identity(modality: Modality) -> None:
    assert schema_fingerprint(get_schema(modality)) == RES103_FINGERPRINTS[modality]
    assert schema_version_of(get_schema(modality)) == SCHEMA_VERSION


def test_pose_contract_v2_represents_unavailable_joints_honestly() -> None:
    pose = get_schema(Modality.POSE)
    assert schema_version_of(pose) == "2"
    assert schema_fingerprint(pose) == POSE_V2_FINGERPRINT

    availability = pose.field("is_available")
    assert availability.type == pa.bool_()
    assert not availability.nullable

    for name in ("x_m", "y_m", "z_m"):
        field_ = pose.field(name)
        assert field_.nullable
        assert nullable_reason_of(field_)
        assert si_unit_of(field_) == "m"
        assert axis_of(field_) == name[0]

    parent = pose.field("parent_joint_id")
    assert parent.nullable
    assert "landmark_set" in (nullable_reason_of(parent) or "")

    error = pose.field("error_m")
    assert error.nullable
    assert "90th-percentile" in (error.metadata or {}).get(b"dynamis.description", b"").decode()


def test_revised_contracts_are_versioned_and_additive() -> None:
    # RES-98 added force_z_body_weight_ratio and made accelerometer-only IMU
    # gyro channels nullable; RES-99 made pose coordinates availability-gated.
    # Each contract carries its own revision.
    assert schema_version_of(get_schema(Modality.IMU)) == "2"
    assert schema_version_of(get_schema(Modality.FORCE)) == "2"
    assert schema_version_of(get_schema(Modality.POSE)) == "2"
    imu = get_schema(Modality.IMU)
    assert imu.field("gyro_x_rad_s").nullable
    assert nullable_reason_of(imu.field("gyro_x_rad_s"))
    force = get_schema(Modality.FORCE)
    ratio = force.field("force_z_body_weight_ratio")
    assert ratio.type == pa.float64()
    assert si_unit_of(ratio) == "1"
    assert axis_of(ratio) == "z"
    assert ratio.nullable and nullable_reason_of(ratio)
