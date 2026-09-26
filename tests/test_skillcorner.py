"""SkillCorner adapter: synthetic structure, canonical contracts and V&V.

CI uses only structurally synthetic files. The real full-match E2E runs locally
against immutable Bronze and is never committed.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

import synthetic_skillcorner as synthetic
from dynamis.adapters.skillcorner.adapter import SkillCornerMatchAdapter
from dynamis.adapters.skillcorner.authorities import (
    POSE_DISPLAY_CONNECTIONS,
    POSE_LANDMARKS,
    POSE_SKELETON_ID,
    SKILLCORNER_DATASET_ID,
)
from dynamis.adapters.skillcorner.pose import analyse_coincidences
from dynamis.adapters.skillcorner.tracking import match_time_ns
from dynamis.contracts import MeasurementClass, Modality, SkeletonTopology
from dynamis.pipeline.ingest import ingest_skillcorner_match
from dynamis.quality.checks import validate


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return synthetic.write_skillcorner_bundle(tmp_path_factory.mktemp("skillcorner"))


def test_match_time_parser_is_exact_and_strict() -> None:
    assert match_time_ns("00:00:00.00") == 0
    assert match_time_ns("00:00:00.04") == 40_000_000
    assert match_time_ns("00:45:00.00") == 2_700_000_000_000
    assert match_time_ns("01:36:45.00") == (96 * 60 + 45) * 1_000_000_000
    for invalid in ("", "90:00", "00:60:00.00", "00:00:60.00", "00:00:00.0", "abc"):
        with pytest.raises(ValueError):
            match_time_ns(invalid)
    with pytest.raises(ValueError):
        match_time_ns(None)


def test_metadata_preserves_half_direction_and_goalkeeper_acronym(
    bundle: dict[str, Path],
) -> None:
    from dynamis.adapters.skillcorner.metadata import parse_match_metadata

    metadata = parse_match_metadata(bundle["match_json"])
    assert metadata.attacking_direction(metadata.home_team_id, 1) == "left_to_right"
    assert metadata.attacking_direction(metadata.away_team_id, 1) == "right_to_left"
    assert metadata.attacking_direction(metadata.home_team_id, 2) == "right_to_left"
    goalkeeper = metadata.player("101")
    assert goalkeeper is not None
    assert goalkeeper.position_group == "Other"
    assert goalkeeper.position_acronym == "GK"
    assert goalkeeper.is_goalkeeper


def test_landmark_authority_is_the_documented_readme_order() -> None:
    from dynamis.adapters.skillcorner.authorities import pose_skeleton

    skeleton = pose_skeleton()
    assert skeleton.skeleton_id == POSE_SKELETON_ID
    assert skeleton.topology is SkeletonTopology.LANDMARK_SET
    assert skeleton.joint_count == 29
    assert tuple(joint.joint_name for joint in skeleton.joints) == POSE_LANDMARKS
    assert all(joint.parent_joint_id is None for joint in skeleton.joints)
    assert [
        (connection.start_joint_name, connection.end_joint_name)
        for connection in skeleton.display_connections
    ] == list(POSE_DISPLAY_CONNECTIONS)
    assert len(skeleton.display_connections) == 28
    # The provider JSON mapping order is alphabetical; it must not leak in.
    assert POSE_LANDMARKS[:4] == ("nose", "neck", "lEye", "rEye")


def test_adapter_domain_declares_pose_skeleton_and_sync_alignments(bundle: dict[str, Path]) -> None:
    adapter = SkillCornerMatchAdapter(
        match_json_path=bundle["match_json"],
        tracking_path=bundle["tracking"],
        pose_zip_path=bundle["pose_zip"],
        version="synthetic",
    )
    domain = adapter.domain()
    assert domain.session is not None
    assert domain.session.session_id == "9000001"
    assert len(domain.subjects) == len(synthetic.PLAYERS)
    pose_streams = [stream for stream in domain.streams if stream.modality is Modality.POSE]
    tracking_streams = [stream for stream in domain.streams if stream.modality is Modality.TRACKING]
    assert len(pose_streams) == 2 and len(tracking_streams) == 2
    for stream in tracking_streams:
        assert stream.stream_metadata["pitch_dimensions_m"] == {
            "length_m": adapter.metadata.pitch_length_m,
            "width_m": adapter.metadata.pitch_width_m,
        }
    assert all(stream.skeleton_id == POSE_SKELETON_ID for stream in pose_streams)
    assert all(
        stream.measurement_class is MeasurementClass.MODEL_ESTIMATED for stream in domain.streams
    )
    skeleton = domain.authorities.skeletons[0]
    assert skeleton.topology is SkeletonTopology.LANDMARK_SET
    assert len(domain.authorities.alignments) == 2
    sports = domain.sports_contexts[0]
    assert sports.sport.code == "football"
    assert sports.competition is None  # this accepted match.json has no competition fact
    assert sports.contest.competition_edition_id is None
    assert len(sports.teams) == 2 and len(sports.periods) == 2
    assert all(
        team.team_id not in {adapter.metadata.home_team_id, adapter.metadata.away_team_id}
        for team in sports.teams
    )
    assert len(domain.authorities.surface_geometries) == 1
    assert domain.authorities.surface_geometries[0].dimensions == {
        "length_m": adapter.metadata.pitch_length_m,
        "width_m": adapter.metadata.pitch_width_m,
    }
    assert domain.authorities.clock_mappings[0].to_canonical_ns(2700) == 2_700_000_000_000
    for alignment in domain.authorities.alignments:
        assert alignment.offset_ns == 0
        assert alignment.scale == 1.0
        assert alignment.source_stream_id.startswith("pose-period-")
        assert alignment.target_stream_id == alignment.source_stream_id.replace(
            "pose-", "tracking-"
        )


def test_synthetic_skillcorner_ingest_is_reconciled_and_contract_clean(
    tmp_settings, bundle: dict[str, Path]
) -> None:
    result = ingest_skillcorner_match(
        tmp_settings,
        match_json_path=bundle["match_json"],
        tracking_path=bundle["tracking"],
        pose_zip_path=bundle["pose_zip"],
        version="synthetic",
    )
    assert result.dataset_id == SKILLCORNER_DATASET_ID
    assert result.reconciliation.all_balanced
    streams = {item.stream_id: item for item in result.streams}
    assert set(streams) == {
        "tracking-period-1",
        "tracking-period-2",
        "pose-period-1",
        "pose-period-2",
    }
    # Tracking: players 4/frame, ball canonical only when X/Y exist.
    assert streams["tracking-period-1"].row_count == 23
    assert streams["tracking-period-2"].row_count == 14
    # Pose: 5 player-frames with pose in period 1, 3 in period 2, 29 joints each.
    assert streams["pose-period-1"].row_count == 145
    assert streams["pose-period-2"].row_count == 87

    # The pose archive member is never expanded next to the canonical output.
    member_plaintext = list(tmp_settings.dataset_root.rglob("9000001.jsonl"))
    assert member_plaintext == []

    pose_table = pq.read_table(streams["pose-period-1"].absolute_path)
    assert validate(pose_table, pose_table.schema) == ()
    assert set(pose_table.column("measurement_class").to_pylist()) == {"MODEL_ESTIMATED"}
    first_frame = pose_table.slice(0, 29)
    assert first_frame.column("joint_name").to_pylist() == list(POSE_LANDMARKS)
    assert first_frame.column("parent_joint_id").to_pylist() == [None] * 29
    assert first_frame.column("error_m").to_pylist() == pytest.approx(
        [(index + 1) * 0.01 for index in range(29)], abs=1e-12
    )
    # The unavailable joint is an explicit row with null coordinates, never imputed.
    names = pose_table.column("joint_name").to_pylist()
    availability = pose_table.column("is_available").to_pylist()
    unavailable_indices = [
        index
        for index, (name, available) in enumerate(zip(names, availability, strict=True))
        if name == "neck" and not available
    ]
    assert len(unavailable_indices) == 1
    row_index = unavailable_indices[0]
    for column in ("x_m", "y_m", "z_m"):
        assert pose_table.column(column)[row_index].as_py() is None
    assert pose_table.column("error_m")[row_index].as_py() == pytest.approx(0.02)
    sync = result.reconciliation.domain["pose_tracking_sync"]
    assert sync["coincident_frame_pairs"] == 5
    assert sync["timestamp_matches"] == 5
    assert sync["timestamp_mismatches"] == 0
    assert sync["matched_player_observations"] == 8
    assert sync["xy_residual_count"] == 8
    assert sync["correction_applied"] is False
    # Exact expected residuals from the synthetic geometry (never forced to zero).
    import math

    far = math.hypot(1.0, 0.8)
    mid = math.hypot(0.1, 0.2)
    expected_residuals = [0.2, far, mid, 0.2, far, 0.2, 0.2, far]
    assert sync["xy_residual_max_m"] == pytest.approx(max(expected_residuals))
    assert sync["xy_residual_mean_m"] == pytest.approx(
        sum(expected_residuals) / len(expected_residuals)
    )

    pose_summaries = result.reconciliation.domain["pose"]
    assert pose_summaries["pose-period-1"]["unavailable_joints"] == 1
    assert pose_summaries["pose-period-1"]["observed_joints"] == 144
    assert pose_summaries["pose-period-1"]["error_observed"] == 145
    assert pose_summaries["pose-period-2"]["unavailable_joints"] == 0


def test_coincidence_analysis_reports_without_forcing_equality(bundle: dict[str, Path]) -> None:
    report = analyse_coincidences(
        pose_zip_path=bundle["pose_zip"],
        tracking_path=bundle["tracking"],
        match_id="9000001",
    )
    assert report.coincident_frame_pairs == 5
    assert report.timestamp_mismatches == 0
    assert report.pose_only_player_observations == 0
    assert report.tracking_only_player_observations == 12
    assert report.xy_residual_median_m is not None
    assert report.xy_residual_p90_m is not None


def test_pose_quarantines_malformed_landmark_mappings(tmp_path: Path, tmp_settings) -> None:
    import json
    import zipfile

    import synthetic_skillcorner as synth
    from dynamis.adapters.skillcorner.metadata import parse_match_metadata
    from dynamis.adapters.skillcorner.pose import PoseCanonicalizer

    match_json = synth.write_match_json(tmp_path / "9000001_match.json")
    frames = []
    for period, first, last in ((1, 0, 0),):
        for frame in range(first, last + 1):
            payload = synth.pose_frame(frame, period=period)
            player = payload["player_data"][0]
            joints = dict(player["joints"])
            joints.pop("nose")  # published landmark absent
            joints["invented"] = {"xyz": [0.0, 0.0, 0.0], "p90_mae_cm": 1.0}
            player["joints"] = joints
            frames.append(json.dumps(payload))
    zip_path = tmp_path / "9000001.jsonl.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("9000001.jsonl", "\n".join(frames) + "\n")

    canonicalizer = PoseCanonicalizer(zip_path, parse_match_metadata(match_json))
    stream = canonicalizer.stream(1)
    rows = list(stream.batches)
    assert rows and sum(batch.num_rows for batch in rows) == 57
    summary = canonicalizer.summary(1)
    assert summary.declared_joint_records == 59
    assert summary.canonical_rows == 57
    assert summary.quarantined_rows == 2
    details = {record.detail for record in summary.quarantined}
    assert any("nose" in detail for detail in details)
    assert any("invented" in detail for detail in details)


def test_pose_quarantines_posed_frames_outside_declared_periods(
    tmp_path: Path,
) -> None:
    import json
    import zipfile

    import synthetic_skillcorner as synth
    from dynamis.adapters.skillcorner.metadata import parse_match_metadata
    from dynamis.adapters.skillcorner.pose import PoseCanonicalizer

    match_json = synth.write_match_json(tmp_path / "9000001_match.json")
    payload = synth.pose_frame(0, period=1)
    payload["period"] = None
    payload["player_data"][0]["joints"] = ["not", "a", "mapping"]
    payload["player_data"][1]["joints"] = synth.joints_for(player_id=102, frame=0)
    undeclared = synth.pose_frame(1, period=1)
    undeclared["period"] = 99
    undeclared["player_data"][0]["joints"] = synth.joints_for(player_id=101, frame=1)
    zip_path = tmp_path / "9000001.jsonl.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "9000001.jsonl", json.dumps(payload) + "\n" + json.dumps(undeclared) + "\n"
        )

    canonicalizer = PoseCanonicalizer(zip_path, parse_match_metadata(match_json))
    stream = canonicalizer.stream(1)
    assert list(stream.batches) == []
    summary = canonicalizer.summary(1)
    # One malformed container (29 authority slots) + one 29-joint mapping + the
    # undeclared-period frame's 29 joints.
    assert summary.declared_joint_records == 87
    assert summary.malformed_joints == 87
    assert summary.canonical_rows == 0
    assert len(summary.quarantined) == 3
    assert any("undeclared period 99" in record.detail for record in summary.quarantined)


def test_pose_quarantines_non_object_landmark_values(
    tmp_path: Path,
) -> None:
    import json
    import zipfile

    import synthetic_skillcorner as synth
    from dynamis.adapters.skillcorner.metadata import parse_match_metadata
    from dynamis.adapters.skillcorner.pose import PoseCanonicalizer

    match_json = synth.write_match_json(tmp_path / "9000001_match.json")
    payload = synth.pose_frame(0, period=1)
    joints = dict(payload["player_data"][0]["joints"])
    joints["nose"] = "not-a-position"
    payload["player_data"][0]["joints"] = joints
    zip_path = tmp_path / "9000001.jsonl.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("9000001.jsonl", json.dumps(payload) + "\n")

    canonicalizer = PoseCanonicalizer(zip_path, parse_match_metadata(match_json))
    stream = canonicalizer.stream(1)
    rows = list(stream.batches)
    assert rows
    summary = canonicalizer.summary(1)
    assert summary.malformed_joints == 1
    assert summary.canonical_rows == 57  # 2 player-frames x 29 joints minus the bad one
    assert any("neither null nor an object" in record.detail for record in summary.quarantined)


def test_ingest_never_regenerates_plaintext_and_is_deterministic(
    tmp_settings, bundle: dict[str, Path]
) -> None:
    first = ingest_skillcorner_match(
        tmp_settings,
        match_json_path=bundle["match_json"],
        tracking_path=bundle["tracking"],
        pose_zip_path=bundle["pose_zip"],
        version="synthetic",
    )
    second = ingest_skillcorner_match(
        tmp_settings,
        match_json_path=bundle["match_json"],
        tracking_path=bundle["tracking"],
        pose_zip_path=bundle["pose_zip"],
        version="synthetic",
    )
    first_checksums = {item.stream_id: item.checksum_sha256 for item in first.streams}
    second_checksums = {item.stream_id: item.checksum_sha256 for item in second.streams}
    assert first_checksums == second_checksums


@pytest.mark.postgres
def test_skillcorner_skeleton_and_alignment_provenance_is_idempotent(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings,
    monkeypatch: pytest.MonkeyPatch,
    bundle: dict[str, Path],
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root
    from dynamis.pipeline.persist import persist_domain, persist_source
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.control_plane import control_plane_engine

    assert postgres_url and test_db_schema
    monkeypatch.setenv(ENV_POSTGRES_URL, postgres_url)
    monkeypatch.setenv(ENV_DB_SCHEMA, test_db_schema)
    root = repository_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "infra" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    admin = create_engine(postgres_url, future=True)
    settings = Settings(
        dataset_root=tmp_settings.dataset_root,
        database_root=tmp_settings.database_root,
        duckdb_path=tmp_settings.duckdb_path,
        db_schema=test_db_schema,
    )
    control = control_plane_engine(settings, postgres_url)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        command.upgrade(config, "head")
        result = ingest_skillcorner_match(
            settings,
            match_json_path=bundle["match_json"],
            tracking_path=bundle["tracking"],
            pose_zip_path=bundle["pose_zip"],
            version="synthetic",
        )
        domain = result.provider_domain
        with control.begin() as connection:
            persist_source(connection, source_by_id(validate_registry(), SKILLCORNER_DATASET_ID))
            first = persist_domain(connection, domain)
            second = persist_domain(connection, domain)
        assert first["skeleton_definition"] == 1
        assert first["skeleton_joint"] == 29
        assert first["sync_alignment"] == 2
        # The sync converges on the current declaration without duplicating rows.
        assert second["skeleton_definition"] == 1
        assert second["skeleton_joint"] == 29
        assert second["sync_alignment"] == 2  # refreshed in place, never duplicated
        with control.connect() as connection:
            topology = connection.execute(
                text("SELECT topology FROM skeleton_definition WHERE skeleton_id = :id"),
                {"id": POSE_SKELETON_ID},
            ).scalar_one()
            display_connections = connection.execute(
                text("SELECT display_connections FROM skeleton_definition WHERE skeleton_id = :id"),
                {"id": POSE_SKELETON_ID},
            ).scalar_one()
            joint_count = connection.execute(
                text("SELECT count(*) FROM skeleton_joint WHERE skeleton_id = :id"),
                {"id": POSE_SKELETON_ID},
            ).scalar_one()
            nullable_parents = connection.execute(
                text(
                    "SELECT count(*) FROM skeleton_joint WHERE skeleton_id = :id "
                    "AND parent_joint_id IS NULL"
                ),
                {"id": POSE_SKELETON_ID},
            ).scalar_one()
            alignments = connection.execute(
                text(
                    "SELECT source_stream_id, target_stream_id, offset_ns, scale "
                    "FROM sync_alignment WHERE dataset_id = :dataset ORDER BY source_stream_id"
                ),
                {"dataset": SKILLCORNER_DATASET_ID},
            ).fetchall()
            pose_streams = connection.execute(
                text(
                    "SELECT count(*) FROM sensor_stream WHERE dataset_id = :dataset "
                    "AND modality = 'pose' AND skeleton_id = :id"
                ),
                {"dataset": SKILLCORNER_DATASET_ID, "id": POSE_SKELETON_ID},
            ).scalar_one()
        assert topology == "landmark_set"
        assert len(display_connections) == 28
        assert int(joint_count) == 29
        assert int(nullable_parents) == 29
        assert int(pose_streams) == 2
        assert alignments == [
            ("pose-period-1", "tracking-period-1", 0, 1.0),
            ("pose-period-2", "tracking-period-2", 0, 1.0),
        ]
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
