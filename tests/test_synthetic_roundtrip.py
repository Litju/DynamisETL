"""Synthetic Arrow -> Parquet(Zstd) -> DuckDB round-trip with known answers.

This is the scientific V&V core of RES-96. Every V1 modality is materialized,
re-read through two independent engines, reconciled against declared
expectations, and checked against independent analytic invariants so a generator
and its expectation cannot simply agree on a shared mistake.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pytest

from dynamis.config import Settings
from dynamis.contracts import (
    Modality,
    get_schema,
    schema_fingerprint,
    schema_version_of,
    time_monotonicity,
)
from dynamis.fixtures.synthetic import (
    EARTH_MEAN_RADIUS_M,
    STANDARD_GRAVITY_M_S2,
    ModalityFixture,
    all_fixtures,
    events_sequence,
    force_bodyweight_static,
    force_dynamic_vertical,
    gnss_constant_velocity,
    gnss_local_offsets,
    imu_deterministic_trace,
    lpt_constant_acceleration,
    pose_skeleton_trajectory,
    tracking_multi_object,
)
from dynamis.quality.checks import validate
from dynamis.storage.duckdb import connect, observe_parquet, query
from dynamis.storage.parquet import (
    content_fingerprint,
    read_parquet_schema,
    read_parquet_table,
    write_parquet_atomic,
)
from dynamis.storage.paths import silver_parquet_path

FIXTURES = all_fixtures()
FIXTURE_IDS = [fixture.name for fixture in FIXTURES]


def _values_match(actual: Any, expected: Any, tolerance: float) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, float):
        return actual is not None and abs(float(actual) - float(expected)) <= tolerance
    return actual == expected


def _reconcile(
    actual_rows: list[dict[str, Any]],
    expected: Mapping[str, tuple[Any, ...]],
    tolerance: float,
) -> None:
    for column, expected_values in expected.items():
        assert column in actual_rows[0], f"column {column!r} missing from the materialized table"
        for index, expected_value in enumerate(expected_values):
            actual_value = actual_rows[index][column]
            assert _values_match(actual_value, expected_value, tolerance), (
                f"{column}[{index}]: stored {actual_value!r} != expected {expected_value!r}"
            )


@pytest.fixture(params=FIXTURES, ids=FIXTURE_IDS)
def fixture(request: pytest.FixtureRequest) -> ModalityFixture:
    return request.param


def test_fixture_satisfies_its_contract(fixture: ModalityFixture) -> None:
    assert validate(fixture.table, fixture.schema) == ()


def test_roundtrip_preserves_schema_rows_and_provenance(
    fixture: ModalityFixture, tmp_settings: Settings
) -> None:
    path = silver_parquet_path(
        tmp_settings,
        dataset_id=fixture.dataset_id,
        modality=fixture.modality,
        session_id=fixture.session_id,
        stream_id=fixture.stream_id,
    )
    written = write_parquet_atomic(fixture.table, path, relative_to=tmp_settings.dataset_root)

    assert written.row_count == fixture.sample_count
    assert written.compression == "zstd"

    stored_schema = read_parquet_schema(path)
    assert stored_schema.names == fixture.schema.names
    assert schema_fingerprint(stored_schema) == written.schema_fingerprint

    connection = connect()
    try:
        observed = observe_parquet(connection, path)
        assert observed.row_count == fixture.sample_count
        assert observed.codecs == ("ZSTD",)
        assert tuple(observed.columns) == tuple(fixture.schema.names)
        assert observed.metadata["dynamis.contract"] == str(
            fixture.schema.metadata[b"dynamis.contract"], "utf-8"
        )
        assert observed.metadata["dynamis.modality"] == fixture.modality.value
        assert observed.metadata["dynamis.units"] == "SI"
        assert observed.metadata["dynamis.schema_version"] == schema_version_of(fixture.schema)

        rows = query(
            connection,
            f"SELECT * FROM read_parquet('{path.as_posix()}') ORDER BY sample_index",
        ).to_pylist()
    finally:
        connection.close()

    assert len(rows) == fixture.sample_count
    _reconcile(rows, fixture.expected, fixture.tolerance)


def test_roundtrip_reconciles_values_through_pyarrow_too(
    fixture: ModalityFixture, tmp_settings: Settings
) -> None:
    path = tmp_settings.dataset_root / f"{fixture.name}.parquet"
    write_parquet_atomic(fixture.table, path)
    rows = read_parquet_table(path).to_pylist()
    _reconcile(rows, fixture.expected, fixture.tolerance)


def test_timing_is_consistent_with_declared_monotonicity(
    fixture: ModalityFixture, tmp_settings: Settings
) -> None:
    path = tmp_settings.dataset_root / f"{fixture.name}.parquet"
    write_parquet_atomic(fixture.table, path)
    rows = read_parquet_table(path).to_pylist()
    schema = get_schema(fixture.modality)
    monotonicity = time_monotonicity(schema)

    indices = [int(row["sample_index"]) for row in rows]
    assert indices == list(range(fixture.sample_count))

    times = [int(row["t_rel_ns"]) for row in rows]
    if monotonicity == "strict":
        assert all(later > earlier for earlier, later in zip(times, times[1:], strict=False))
        if fixture.nominal_sampling_rate_hz is not None:
            for index, value in enumerate(times):
                assert value == fixture.expected_ns(index)
    else:
        # Frame streams (tracking, pose) share one timestamp across the entities
        # of a frame, so time is non-decreasing rather than strictly increasing.
        assert all(later >= earlier for earlier, later in zip(times, times[1:], strict=False))
        assert len(set(times)) < len(times)
        interval_ns = round(1_000_000_000 / float(fixture.nominal_sampling_rate_hz or 1.0))
        assert all(value % interval_ns == 0 for value in times)
        frame_count = len(set(times))
        assert len(times) % frame_count == 0


def test_artifact_checksum_is_reproducible(
    fixture: ModalityFixture, tmp_settings: Settings
) -> None:
    path = tmp_settings.dataset_root / f"{fixture.name}.parquet"
    first = write_parquet_atomic(fixture.table, path)
    second = write_parquet_atomic(fixture.table, path)
    assert first.checksum_sha256 == second.checksum_sha256


def test_fixture_generation_is_deterministic() -> None:
    for fixture in all_fixtures():
        twin = next(item for item in all_fixtures() if item.name == fixture.name)
        assert content_fingerprint(fixture.table) == content_fingerprint(twin.table)
        assert fixture.expected == twin.expected


def test_identity_is_dataset_scoped_and_single_valued(fixture: ModalityFixture) -> None:
    for column in ("dataset_id", "session_id", "stream_id", "clock_id", "synchronization_spec_id"):
        values = {row[column] for row in fixture.table.select([column]).to_pylist()}
        assert values == {getattr(fixture, column)}, column
    assert fixture.table.column("dataset_id")[0].as_py() == "synthetic-foundation"


# ---------------------------------------------------------------------------
# Known-answer tests, independent of the generator's own formulas
# ---------------------------------------------------------------------------


def test_gnss_constant_velocity_is_a_true_constant_velocity_trajectory() -> None:
    fixture = gnss_constant_velocity(speed_m_s=5.0, heading_deg=0.0, rate_hz=10.0)
    latitudes = [float(value) for value in fixture.expected["latitude_deg"]]
    longitudes = [float(value) for value in fixture.expected["longitude_deg"]]

    # Heading 0 means due north: longitude is constant, latitude increases.
    assert longitudes == pytest.approx([longitudes[0]] * len(longitudes), abs=1e-12)
    assert all(later > earlier for earlier, later in zip(latitudes, latitudes[1:], strict=False))

    # Re-derive the step length from latitude/longitude alone and compare it with
    # the analytic expectation v * dt.
    for index in range(1, len(latitudes)):
        delta_north = math.radians(latitudes[index] - latitudes[index - 1]) * EARTH_MEAN_RADIUS_M
        assert delta_north == pytest.approx(5.0 / 10.0, abs=1e-6)


def test_gnss_east_heading_produces_eastward_motion() -> None:
    east_fixture = gnss_constant_velocity(speed_m_s=3.0, heading_deg=90.0, rate_hz=10.0)
    latitudes = [float(value) for value in east_fixture.expected["latitude_deg"]]
    longitudes = [float(value) for value in east_fixture.expected["longitude_deg"]]
    assert latitudes == pytest.approx([latitudes[0]] * len(latitudes), abs=1e-9)
    assert all(later > earlier for earlier, later in zip(longitudes, longitudes[1:], strict=False))
    east, north = gnss_local_offsets(east_fixture)
    assert north[-1] == pytest.approx(0.0, abs=1e-6)
    assert east[-1] == pytest.approx(3.0 * (len(east) - 1) / 10.0, rel=1e-9)


def test_imu_trace_matches_analytic_properties() -> None:
    fixture = imu_deterministic_trace(amplitude_m_s2=2.0, frequency_hz=1.0, rate_hz=100.0)
    accel_x = [float(value) for value in fixture.expected["accel_x_m_s2"]]
    accel_z = [float(value) for value in fixture.expected["accel_z_m_s2"]]
    gyro_z = [float(value) for value in fixture.expected["gyro_z_rad_s"]]

    assert accel_z == pytest.approx([STANDARD_GRAVITY_M_S2] * len(accel_z))
    assert gyro_z == pytest.approx([1.5] * len(gyro_z))
    # Two complete sinusoid periods: the discrete mean is exactly zero.
    assert sum(accel_x) / len(accel_x) == pytest.approx(0.0, abs=1e-12)
    assert max(accel_x) == pytest.approx(2.0, rel=1e-6)
    assert min(accel_x) == pytest.approx(-2.0, rel=1e-6)


def test_static_force_equals_body_weight() -> None:
    fixture = force_bodyweight_static(mass_kg=80.0, rate_hz=1000.0, duration_s=1.0)
    forces = [float(value) for value in fixture.expected["force_z_n"]]
    expected_weight = 80.0 * STANDARD_GRAVITY_M_S2

    assert forces == pytest.approx([expected_weight] * len(forces))
    impulse = sum(forces) / 1000.0
    assert impulse == pytest.approx(expected_weight * 1.0, rel=1e-12)


def test_dynamic_force_has_analytically_known_impulse_and_extremes() -> None:
    fixture = force_dynamic_vertical(
        mass_kg=80.0, rate_hz=1000.0, duration_s=1.0, frequency_hz=1.0, mid_scale=1.5
    )
    forces = [float(value) for value in fixture.expected["force_z_n"]]
    body_weight = 80.0 * STANDARD_GRAVITY_M_S2

    # A whole number of sinusoid cycles means the mean equals the mid scale.
    assert sum(forces) / len(forces) == pytest.approx(1.5 * body_weight, rel=1e-6)
    assert max(forces) == pytest.approx(2.5 * body_weight, rel=1e-4)
    assert min(forces) == pytest.approx(0.5 * body_weight, rel=1e-4)
    assert all(value > 0.0 for value in forces)


def test_lpt_position_and_velocity_are_analytic_and_mutually_consistent() -> None:
    fixture = lpt_constant_acceleration(
        rate_hz=100.0,
        sample_count=100,
        initial_velocity_m_s=0.2,
        acceleration_m_s2=1.5,
    )
    positions = [float(value) for value in fixture.expected["position_m"]]
    velocities = [float(value) for value in fixture.expected["velocity_m_s"]]
    dt = 1.0 / 100.0

    # Central differences of position must reproduce the analytic velocity
    # without using the fixture's velocity column.
    for index in range(1, len(positions) - 1):
        numeric = (positions[index + 1] - positions[index - 1]) / (2.0 * dt)
        assert numeric == pytest.approx(velocities[index], abs=1e-9)

    second_difference = (positions[2] - 2.0 * positions[1] + positions[0]) / (dt * dt)
    assert second_difference == pytest.approx(1.5, rel=1e-9)


def test_tracking_stream_carries_multiple_objects_with_per_object_identity() -> None:
    fixture = tracking_multi_object(rate_hz=25.0, frame_count=50, player_speed_m_s=4.0)
    object_ids = fixture.expected["object_id"]
    subjects = fixture.expected["subject_id"]
    groups = fixture.expected["group_id"]
    xs = [float(value) for value in fixture.expected["x_m"]]

    assert len(set(object_ids)) == 3
    assert set(subjects) == {"syn-subject-0001", "syn-subject-0002", None}
    assert set(groups) == {"team-home", None}
    assert fixture.table.num_rows == 150

    xs_by_object: dict[str, list[float]] = {}
    for index, object_id in enumerate(object_ids):
        xs_by_object.setdefault(object_id, []).append(xs[index])

    # Per-object displacement per frame is exactly speed / rate, with opposite
    # directions for the two players.
    for object_id, sign in (("syn-player-01", 1.0), ("syn-player-02", -1.0)):
        values = xs_by_object[object_id]
        steps = [later - earlier for earlier, later in zip(values, values[1:], strict=False)]
        assert steps == pytest.approx([sign * 4.0 / 25.0] * len(steps), rel=1e-9)
    assert xs_by_object["syn-ball-01"] == pytest.approx([10.0] * 50)


def test_events_have_deterministic_ordered_timestamps() -> None:
    fixture = events_sequence()
    times = [int(value) for value in fixture.expected["t_rel_ns"]]
    assert times == sorted(times)
    assert len(times) == 5
    assert times[0] == 0
    assert times[-1] == 2_700_000_000_000

    rows = fixture.table.to_pylist()
    kickoff = next(row for row in rows if row["event_id"] == "evt-kickoff")
    assert kickoff["x_m"] is None
    assert kickoff["provider_player_id"] is None
    assert kickoff["nominal_sampling_rate_hz"] is None

    goal = next(row for row in rows if row["event_id"] == "evt-goal-1")
    assert goal["x_m"] == pytest.approx(52.0)
    assert goal["provider_player_id"] == "syn-player-02"


def test_pose_skeleton_has_explicit_topology_confidence_and_error() -> None:
    fixture = pose_skeleton_trajectory(rate_hz=25.0, frame_count=50)
    rows = fixture.table.to_pylist()
    assert fixture.table.num_rows == 150

    # Three joints share each frame timestamp.
    frame_times = [int(row["t_rel_ns"]) for row in rows[::3]]
    assert len(frame_times) == 50
    assert frame_times == sorted(frame_times)
    for frame in range(50):
        block = rows[frame * 3 : frame * 3 + 3]
        assert len({int(item["t_rel_ns"]) for item in block}) == 1
        assert [int(item["joint_id"]) for item in block] == [0, 1, 2]
        assert [item["joint_name"] for item in block] == ["pelvis", "knee_right", "ankle_right"]
        assert [item["parent_joint_id"] for item in block] == [None, 0, 1]
        assert all(item["is_available"] for item in block)

    occluded = [row for row in rows if row["is_occluded"]]
    assert occluded, "the fixture must exercise occlusion metadata"
    for row in occluded:
        assert float(row["confidence"]) < 0.5
        assert float(row["error_m"]) > 0.0
    for row in rows:
        assert 0.0 <= float(row["confidence"]) <= 1.0
        assert row["x_m"] == 0.0


def test_pose_unavailable_joints_carry_null_coordinates_and_are_never_imputed() -> None:
    fixture = pose_skeleton_trajectory(rate_hz=25.0, frame_count=10, unavailable_pattern=True)
    rows = fixture.table.to_pylist()
    unavailable = [row for row in rows if not row["is_available"]]
    assert unavailable, "the fixture must exercise explicit unavailability"
    for row in unavailable:
        assert row["x_m"] is None
        assert row["y_m"] is None
        assert row["z_m"] is None
        assert row["error_m"] is None
        assert row["is_occluded"] is True
    observed = [row for row in rows if row["is_available"]]
    assert observed
    for row in observed:
        assert row["x_m"] is not None and row["y_m"] is not None and row["z_m"] is not None
    from dynamis.quality.checks import check_pose_payload_completeness

    assert check_pose_payload_completeness(fixture.table, fixture.schema) == ()


def test_fixtures_cover_every_modality() -> None:
    modalities = {fixture.modality for fixture in all_fixtures()}
    assert modalities == set(Modality)
    force_fixtures = [item for item in all_fixtures() if item.modality is Modality.FORCE]
    assert len(force_fixtures) == 2
