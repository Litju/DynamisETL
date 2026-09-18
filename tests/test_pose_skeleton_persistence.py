"""Skeleton authorities persist through ProviderDomain before pose streams.

The PostgreSQL suite is gated on ``DYNAMIS_TEST_POSTGRES_URL``. It proves that a
tree skeleton and a landmark_set skeleton (no source parent graph) survive the
control plane intact, that reruns are idempotent, and that the pre-RES-99 schema
cannot silently relabel landmark evidence as a tree on downgrade.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from dynamis.config import ENV_DB_SCHEMA, ENV_POSTGRES_URL, Settings, repository_root
from dynamis.contracts import (
    Clock,
    JointDefinition,
    MeasurementClass,
    Modality,
    SensorStream,
    Session,
    SkeletonDefinition,
    SkeletonTopology,
    SynchronizationMethod,
    SynchronizationSpec,
    Timebase,
)
from dynamis.pipeline.streams import ProviderDomain, SourceAuthorities

DATASET_ID = "skillcorner-opendata"
SESSION_ID = "session-a"

TREE = SkeletonDefinition(
    skeleton_id="skel-tree",
    name="tree skeleton",
    joint_count=2,
    joints=(
        JointDefinition(joint_id=0, joint_name="pelvis", parent_joint_id=None),
        JointDefinition(joint_id=1, joint_name="knee_right", parent_joint_id=0),
    ),
)

LANDMARKS = SkeletonDefinition(
    skeleton_id="skel-landmarks",
    name="landmark set skeleton",
    topology=SkeletonTopology.LANDMARK_SET,
    joint_count=3,
    joints=(
        JointDefinition(joint_id=0, joint_name="left_ankle", parent_joint_id=None),
        JointDefinition(joint_id=1, joint_name="right_ankle", parent_joint_id=None),
        JointDefinition(joint_id=2, joint_name="pelvis", parent_joint_id=None),
    ),
    description="Source publishes an ordered landmark list with no parent graph.",
)


def _domain(*, pose_stream: bool = False) -> ProviderDomain:
    streams: tuple[SensorStream, ...] = ()
    if pose_stream:
        streams = (
            SensorStream(
                dataset_id=DATASET_ID,
                session_id=SESSION_ID,
                stream_id="pose-00000001",
                modality=Modality.POSE,
                measurement_class=MeasurementClass.MODEL_ESTIMATED,
                clock_id="clock-a",
                synchronization_spec_id="sync-a",
                skeleton_id=LANDMARKS.skeleton_id,
            ),
        )
    return ProviderDomain(
        session=None,
        sessions=(Session(dataset_id=DATASET_ID, session_id=SESSION_ID),),
        subjects=(),
        participants=(),
        trials=(),
        streams=streams,
        authorities=SourceAuthorities(
            clocks=(Clock(clock_id="clock-a", timebase=Timebase.SESSION_MONOTONIC),),
            synchronizations=(
                SynchronizationSpec(
                    sync_spec_id="sync-a",
                    method=SynchronizationMethod.SOURCE_PROVIDED,
                    reference_clock_id="clock-a",
                    notes="declared by the source",
                ),
            ),
            skeletons=(TREE, LANDMARKS),
        ),
    )


def test_landmark_set_skeleton_contract_has_no_parent_graph() -> None:
    assert LANDMARKS.topology is SkeletonTopology.LANDMARK_SET
    assert all(joint.parent_joint_id is None for joint in LANDMARKS.joints)
    assert TREE.topology is SkeletonTopology.TREE


@pytest.mark.postgres
def test_skeleton_authorities_round_trip_and_are_idempotent(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from dynamis.pipeline.persist import persist_domain, persist_source
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.control_plane import control_plane_engine

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

        with control.begin() as connection:
            persist_source(connection, source_by_id(validate_registry(), DATASET_ID))
            first = persist_domain(connection, _domain(pose_stream=True))
            second = persist_domain(connection, _domain(pose_stream=True))

        assert first["skeleton_definition"] == 2
        assert first["skeleton_joint"] == 5
        # A rerun converges on the current declaration: it never duplicates rows
        # and never leaves a stale definition or joint behind.
        assert second["skeleton_definition"] == 2
        assert second["skeleton_joint"] == 5
        assert first["sensor_stream"] == 1  # the pose stream precedes nothing wrongly

        with control.connect() as connection:
            definitions = connection.execute(
                text(
                    "SELECT skeleton_id, topology, joint_count FROM skeleton_definition "
                    "ORDER BY skeleton_id"
                )
            ).fetchall()
            joints = connection.execute(
                text(
                    "SELECT skeleton_id, joint_id, joint_name, parent_joint_id "
                    "FROM skeleton_joint ORDER BY skeleton_id, joint_id"
                )
            ).fetchall()
            stream = connection.execute(
                text("SELECT skeleton_id FROM sensor_stream WHERE stream_id = 'pose-00000001'")
            ).scalar_one()

        assert definitions == [
            ("skel-landmarks", "landmark_set", 3),
            ("skel-tree", "tree", 2),
        ]
        assert joints == [
            ("skel-landmarks", 0, "left_ankle", None),
            ("skel-landmarks", 1, "right_ankle", None),
            ("skel-landmarks", 2, "pelvis", None),
            ("skel-tree", 0, "pelvis", None),
            ("skel-tree", 1, "knee_right", 0),
        ]
        assert stream == "skel-landmarks"

        # A changed declaration under the same skeleton identity replaces stale
        # definition fields and drops joints the new declaration no longer has.
        modified = SkeletonDefinition(
            skeleton_id=LANDMARKS.skeleton_id,
            name="landmark set v2",
            topology=SkeletonTopology.LANDMARK_SET,
            joint_count=2,
            joints=(
                JointDefinition(joint_id=0, joint_name="left_ankle", parent_joint_id=None),
                JointDefinition(joint_id=1, joint_name="right_knee", parent_joint_id=None),
            ),
            description="Revised landmark list for the convergence regression.",
        )
        revised_domain = ProviderDomain(
            session=None,
            sessions=(Session(dataset_id=DATASET_ID, session_id=SESSION_ID),),
            subjects=(),
            participants=(),
            trials=(),
            streams=_domain(pose_stream=True).streams,
            authorities=SourceAuthorities(
                clocks=_domain(pose_stream=True).authorities.clocks,
                synchronizations=_domain(pose_stream=True).authorities.synchronizations,
                skeletons=(TREE, modified),
            ),
        )
        with control.begin() as connection:
            persist_domain(connection, revised_domain)
        with control.connect() as connection:
            revised = connection.execute(
                text(
                    "SELECT d.name, d.joint_count, j.joint_id, j.joint_name, j.parent_joint_id "
                    "FROM skeleton_definition d JOIN skeleton_joint j USING (skeleton_id) "
                    "WHERE d.skeleton_id = :id ORDER BY j.joint_id"
                ),
                {"id": LANDMARKS.skeleton_id},
            ).fetchall()
        assert revised == [
            ("landmark set v2", 2, 0, "left_ankle", None),
            ("landmark set v2", 2, 1, "right_knee", None),
        ]
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()


@pytest.mark.postgres
def test_skeleton_topology_downgrade_refuses_persisted_landmark_evidence(
    postgres_url: str,
    test_db_schema: str,
    tmp_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from dynamis.pipeline.persist import persist_domain, persist_source
    from dynamis.registry import source_by_id, validate_registry
    from dynamis.storage.control_plane import control_plane_engine

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
        with control.begin() as connection:
            persist_source(connection, source_by_id(validate_registry(), DATASET_ID))
            persist_domain(connection, _domain(pose_stream=True))

        with pytest.raises(RuntimeError, match="cannot downgrade 0004"):
            command.downgrade(config, "0003_sync_alignment")

        # Only tree rows remain: the transition is representable and proceeds.
        with admin.begin() as connection:
            connection.execute(text(f'SET search_path TO "{test_db_schema}", public'))
            connection.execute(
                text("DELETE FROM sensor_stream WHERE dataset_id = :dataset_id"),
                {"dataset_id": DATASET_ID},
            )
            connection.execute(
                text("DELETE FROM skeleton_joint WHERE skeleton_id = 'skel-landmarks'")
            )
            connection.execute(
                text("DELETE FROM skeleton_definition WHERE skeleton_id = 'skel-landmarks'")
            )
        command.downgrade(config, "0003_sync_alignment")
        with admin.connect() as connection:
            revision = connection.execute(
                text(f'SELECT version_num FROM "{test_db_schema}".alembic_version')
            ).scalar_one()
            has_topology = connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    f"WHERE table_schema = '{test_db_schema}' "
                    "AND table_name = 'skeleton_definition' AND column_name = 'topology'"
                )
            ).scalar_one()
        assert revision == "0003_sync_alignment"
        assert int(has_topology) == 0
    finally:
        control.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{test_db_schema}" CASCADE'))
        admin.dispose()
