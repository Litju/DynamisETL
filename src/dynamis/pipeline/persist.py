"""Control-plane persistence for real ingestions.

The dense samples stay in Parquet; PostgreSQL receives the semantic and
provenance envelope only: source/version/files, subjects/participants/trials,
declared authorities (clocks, frames, synchronization), streams, materialized
artifact metadata, processing runs and quality findings.

Every statement is an idempotent upsert so re-running the same ingestion does
not duplicate control-plane rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Engine, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from dynamis.config import Settings
from dynamis.contracts import (
    AlgorithmSpec,
    DatasetSource,
    ProcessingRun,
    ProcessingStatus,
    SkeletonDefinition,
)
from dynamis.pipeline.ingest import IngestResult
from dynamis.pipeline.streams import ProviderDomain
from dynamis.registry import source_by_id, validate_registry
from dynamis.storage.manifest import read_bronze_manifest
from dynamis.storage.metadata import build_metadata

_TABLES = build_metadata().tables

ALGORITHM_SPEC_TABLE = _TABLES["algorithm_spec"]
CLOCK_TABLE = _TABLES["clock"]
COORDINATE_FRAME_TABLE = _TABLES["coordinate_frame"]
DATASET_SOURCE_TABLE = _TABLES["dataset_source"]
DATASET_SOURCE_MODALITY_TABLE = _TABLES["dataset_source_modality"]
DATASET_VERSION_TABLE = _TABLES["dataset_version"]
DATASET_VERSION_FILE_TABLE = _TABLES["dataset_version_file"]
DERIVED_METRIC_TABLE = _TABLES["derived_metric"]
DEVICE_TABLE = _TABLES["device"]
LICENSE_POLICY_TABLE = _TABLES["license_policy"]
PROCESSING_ARTIFACT_TABLE = _TABLES["processing_artifact"]
PROCESSING_RUN_TABLE = _TABLES["processing_run"]
QUALITY_ISSUE_TABLE = _TABLES["quality_issue"]
SAMPLE_ARTIFACT_TABLE = _TABLES["sample_artifact"]
SENSOR_STREAM_TABLE = _TABLES["sensor_stream"]
SESSION_TABLE = _TABLES["session"]
SESSION_PARTICIPANT_TABLE = _TABLES["session_participant"]
SKELETON_DEFINITION_TABLE = _TABLES["skeleton_definition"]
SKELETON_JOINT_TABLE = _TABLES["skeleton_joint"]
SUBJECT_TABLE = _TABLES["subject"]
SYNC_ALIGNMENT_TABLE = _TABLES["sync_alignment"]
SYNCHRONIZATION_SPEC_TABLE = _TABLES["synchronization_spec"]
TRIAL_TABLE = _TABLES["trial"]

#: Identity columns of ``sync_alignment``; the alignment is deterministic and
#: never generates a random identifier.
SYNC_ALIGNMENT_KEY = (
    "dataset_id",
    "source_stream_id",
    "target_stream_id",
    "sync_spec_id",
)


def processing_run_notes(*, dataset_id: str, session_id: str, algorithm_id: str) -> str:
    """Deterministic, issue-agnostic provenance text for an ingestion run.

    A processing run must describe *what actually ran* (dataset, session,
    algorithm), never which Linear issue commissioned it: a rerun under the same
    run identity may be executed by different code revisions and a hard-coded
    issue number would silently mislabel it.
    """
    return (
        "DynamisData source ingestion; "
        f"dataset={dataset_id}; session={session_id}; algorithm={algorithm_id}"
    )


@dataclass(frozen=True, slots=True)
class PersistSummary:
    dataset_id: str
    version: str
    run_id: str
    rows_written: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version": self.version,
            "run_id": self.run_id,
            "rows_written": self.rows_written,
        }


def _upsert(connection, table: Table, rows: list[dict[str, Any]]) -> int:
    """Insert-or-ignore, returning the number of rows actually inserted."""
    if not rows:
        return 0
    primary_keys = [column for column in table.primary_key.columns]
    statement = (
        pg_insert(table)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[column.name for column in primary_keys])
        .returning(*primary_keys)
    )
    return len(connection.execute(statement).fetchall())


def _upsert_alignment(connection, rows: list[dict[str, Any]]) -> int:
    """Insert-or-refresh one declared alignment per deterministic identity.

    The identity (dataset, source stream, target stream, sync spec) never
    changes; a rerun whose declared offset, scale or notes changed under the
    same identity converges to the current declaration instead of leaving a
    stale row behind.
    """
    if not rows:
        return 0
    statement = pg_insert(SYNC_ALIGNMENT_TABLE).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=list(SYNC_ALIGNMENT_KEY),
        set_={
            "offset_ns": statement.excluded.offset_ns,
            "scale": statement.excluded.scale,
            "notes": statement.excluded.notes,
        },
    )
    connection.execute(statement)
    # Every row was inserted or refreshed to the current declaration; a driver
    # rowcount is not portable for a multi-row upsert, so report the declared
    # count instead of a driver-specific interpretation.
    return len(rows)


def _sync_skeletons(connection, skeletons: tuple[SkeletonDefinition, ...]) -> tuple[int, int]:
    """Converge skeleton definitions and joints to the current declaration.

    A rerun must neither duplicate rows nor leave a stale definition, a stale
    joint name/parent or a joint the current declaration no longer contains.
    Definitions and joints are upserted in place; joints absent from the
    declaration are deleted *after* the upsert, so no remaining row can still
    reference a deleted parent.
    """
    if not skeletons:
        return 0, 0
    definitions = [
        {
            "skeleton_id": skeleton.skeleton_id,
            "name": skeleton.name,
            "topology": skeleton.topology.value,
            "joint_count": skeleton.joint_count,
            "display_connections": [
                connection.model_dump() for connection in skeleton.display_connections
            ],
            "description": skeleton.description,
        }
        for skeleton in skeletons
    ]
    statement = pg_insert(SKELETON_DEFINITION_TABLE).values(definitions)
    statement = statement.on_conflict_do_update(
        index_elements=["skeleton_id"],
        set_={
            "name": statement.excluded.name,
            "topology": statement.excluded.topology,
            "joint_count": statement.excluded.joint_count,
            "display_connections": statement.excluded.display_connections,
            "description": statement.excluded.description,
        },
    )
    connection.execute(statement)

    joints = [
        {
            "skeleton_id": skeleton.skeleton_id,
            "joint_id": joint.joint_id,
            "joint_name": joint.joint_name,
            "parent_joint_id": joint.parent_joint_id,
        }
        for skeleton in skeletons
        for joint in skeleton.joints
    ]
    if joints:
        insert_joints = pg_insert(SKELETON_JOINT_TABLE).values(joints)
        insert_joints = insert_joints.on_conflict_do_update(
            index_elements=["skeleton_id", "joint_id"],
            set_={
                "joint_name": insert_joints.excluded.joint_name,
                "parent_joint_id": insert_joints.excluded.parent_joint_id,
            },
        )
        connection.execute(insert_joints)
    declared = {
        (skeleton.skeleton_id, joint.joint_id)
        for skeleton in skeletons
        for joint in skeleton.joints
    }
    skeleton_ids = [skeleton.skeleton_id for skeleton in skeletons]
    existing = connection.execute(
        sa.select(SKELETON_JOINT_TABLE.c.skeleton_id, SKELETON_JOINT_TABLE.c.joint_id).where(
            SKELETON_JOINT_TABLE.c.skeleton_id.in_(skeleton_ids)
        )
    ).fetchall()
    stale = [
        (row.skeleton_id, row.joint_id)
        for row in existing
        if (row.skeleton_id, row.joint_id) not in declared
    ]
    if stale:
        connection.execute(
            SKELETON_JOINT_TABLE.delete().where(
                sa.tuple_(SKELETON_JOINT_TABLE.c.skeleton_id, SKELETON_JOINT_TABLE.c.joint_id).in_(
                    stale
                )
            )
        )
    return len(definitions), len(joints)


def _alignment_rows(domain: ProviderDomain) -> list[dict[str, Any]]:
    """Resolve declared alignments against the domain's own streams.

    An alignment is dataset-scoped by construction, so both endpoints must be
    streams of *this* domain; a dangling reference is a programming error, not
    something to persist for a foreign key to reject later.
    """
    stream_dataset = {stream.stream_id: stream.dataset_id for stream in domain.streams}
    rows: list[dict[str, Any]] = []
    for alignment in domain.authorities.alignments:
        source_dataset = stream_dataset.get(alignment.source_stream_id)
        target_dataset = stream_dataset.get(alignment.target_stream_id)
        missing = [
            stream_id
            for stream_id, dataset in (
                (alignment.source_stream_id, source_dataset),
                (alignment.target_stream_id, target_dataset),
            )
            if dataset is None
        ]
        if missing:
            raise ValueError(
                f"declared sync alignment references stream(s) outside the domain: {missing}"
            )
        if source_dataset != target_dataset:
            raise ValueError(
                f"declared sync alignment spans datasets: {source_dataset!r} -> {target_dataset!r}"
            )
        rows.append(
            {
                "dataset_id": source_dataset,
                "source_stream_id": alignment.source_stream_id,
                "target_stream_id": alignment.target_stream_id,
                "sync_spec_id": alignment.sync_spec_id,
                "offset_ns": alignment.offset_ns,
                "scale": alignment.scale,
                "notes": alignment.notes,
            }
        )
    return rows


def _update_source(connection, table: Table, row: dict[str, Any]) -> int:
    """Upsert one registry source so its rights authority tracks the registry.

    ``dataset_source`` is a mirror of registry authority, not immutable
    evidence: when a license is clarified or a scope is corrected, a rerun must
    converge the control-plane link to the current policy instead of leaving the
    source bound to a stale one. Policy rows stay content-addressed, so the
    superseded policy remains auditable.
    """
    statement = pg_insert(table).values([row])
    statement = statement.on_conflict_do_update(
        index_elements=["dataset_id"],
        set_={
            "name": statement.excluded.name,
            "provider": statement.excluded.provider,
            "upstream_urls": statement.excluded.upstream_urls,
            "doi": statement.excluded.doi,
            "domain": statement.excluded.domain,
            "adapter_id": statement.excluded.adapter_id,
            "v1_role": statement.excluded.v1_role,
            "initial_scope": statement.excluded.initial_scope,
            "license_policy_id": statement.excluded.license_policy_id,
        },
    )
    result = connection.execute(statement)
    return int(result.rowcount if result.rowcount and result.rowcount > 0 else 1)


def _update_run(connection, table: Table, row: dict[str, Any]) -> int:
    """Upsert one processing run so a re-run refreshes its state."""
    statement = pg_insert(table).values([row])
    statement = statement.on_conflict_do_update(
        index_elements=["run_id"],
        set_={
            "status": statement.excluded.status,
            "code_git_sha": statement.excluded.code_git_sha,
            "completed_at": statement.excluded.completed_at,
            "input_checksums": statement.excluded.input_checksums,
            "notes": statement.excluded.notes,
        },
    )
    result = connection.execute(statement)
    return int(result.rowcount if result.rowcount and result.rowcount > 0 else 1)


def _replace_by_path(
    connection,
    table: Table,
    rows: list[dict[str, Any]],
    *,
    dataset_id: str,
) -> int:
    """Replace artifact rows for the same (dataset_id, relative_path).

    ``sample_artifact`` describes the *current* materialization of a path and
    ``processing_artifact`` is unique per path too; re-materializing the same
    stream must not leave a stale checksum behind. Historical runs stay
    auditable through ``processing_run`` and the external receipts.
    """
    if not rows:
        return 0
    paths = sorted({str(row["relative_path"]) for row in rows})
    table_delete = table.delete()
    connection.execute(
        table_delete.where(
            sa.and_(table.c.dataset_id == dataset_id, table.c.relative_path.in_(paths))
        )
    )
    return _upsert(connection, table, rows)


def persist_source(connection, source: DatasetSource) -> dict[str, int]:
    """Registry source, license, modalities, version and expected files."""
    written: dict[str, int] = {}
    written["license_policy"] = _upsert(
        connection,
        LICENSE_POLICY_TABLE,
        [
            {
                "policy_id": source.license.policy_id,
                "identifier": source.license.identifier,
                "status": source.license.status.value,
                "attribution_required": source.license.attribution_required,
                "noncommercial_only": source.license.noncommercial_only,
                "share_alike": source.license.share_alike,
                "redistribution": source.license.redistribution.value,
                "local_only": source.license.local_only,
                "restrictions": list(source.license.restrictions),
            }
        ],
    )
    written["dataset_source"] = _update_source(
        connection,
        DATASET_SOURCE_TABLE,
        {
            "dataset_id": source.dataset_id,
            "name": source.name,
            "provider": source.provider,
            "upstream_urls": [str(url) for url in source.upstream_urls],
            "doi": source.doi,
            "domain": source.domain,
            "adapter_id": source.adapter_id,
            "v1_role": source.v1_role,
            "initial_scope": source.initial_scope,
            "license_policy_id": source.license.policy_id,
        },
    )
    written["dataset_source_modality"] = _upsert(
        connection,
        DATASET_SOURCE_MODALITY_TABLE,
        [
            {"dataset_id": source.dataset_id, "modality": modality.value}
            for modality in source.modalities
        ],
    )
    version_rows = [
        {
            "dataset_id": source.dataset_id,
            "version": version.version,
            "release_date": version.release_date,
            "upstream_url": str(version.upstream_url),
            "citation": version.citation,
            "optional": version.optional,
            "retrieval_status": version.retrieval.status.value,
            "retrieved_at": version.retrieval.retrieved_at,
        }
        for version in source.versions
    ]
    written["dataset_version"] = _upsert(connection, DATASET_VERSION_TABLE, version_rows)
    file_rows = [
        {
            "dataset_id": source.dataset_id,
            "version": version.version,
            "key": item.key,
            "size_bytes": item.size_bytes,
            "upstream_md5": None if item.md5 == "unknown" else item.md5,
            "upstream_sha256": None if item.sha256 == "unknown" else item.sha256,
            "local_sha256": item.local_sha256,
            "retrieved_at": item.retrieved_at,
        }
        for version in source.versions
        for item in version.retrieval.files
    ]
    written["dataset_version_file"] = _upsert(connection, DATASET_VERSION_FILE_TABLE, file_rows)
    return written


def persist_bronze_state(
    connection, settings: Settings, *, dataset_id: str, version: str
) -> tuple[str, ...]:
    """Record the verified Bronze retrieval state and return its checksums."""
    manifest = read_bronze_manifest(settings, dataset_id=dataset_id, version=version)
    retrieved = [item for item in manifest.files if item.local_sha256 is not None]
    if retrieved:
        connection.execute(
            DATASET_VERSION_TABLE.update()
            .where(
                DATASET_VERSION_TABLE.c.dataset_id == dataset_id,
                DATASET_VERSION_TABLE.c.version == version,
            )
            .values(retrieval_status="fetched", retrieved_at=manifest.retrieved_at)
        )
        for item in retrieved:
            connection.execute(
                DATASET_VERSION_FILE_TABLE.update()
                .where(
                    DATASET_VERSION_FILE_TABLE.c.dataset_id == dataset_id,
                    DATASET_VERSION_FILE_TABLE.c.version == version,
                    DATASET_VERSION_FILE_TABLE.c.key == item.key,
                )
                .values(
                    local_sha256=item.local_sha256,
                    retrieved_at=item.retrieved_at or manifest.retrieved_at,
                )
            )
    return tuple(item.local_sha256 or "" for item in retrieved)


def persist_domain(connection, domain: ProviderDomain) -> dict[str, int]:
    written: dict[str, int] = {}
    written["subject"] = _upsert(
        connection,
        SUBJECT_TABLE,
        [
            {
                "dataset_id": subject.dataset_id,
                "subject_id": subject.subject_id,
                "sex": subject.sex,
                "cohort": subject.cohort,
                "notes": subject.notes,
            }
            for subject in domain.subjects
        ],
    )
    written["device"] = _upsert(
        connection,
        DEVICE_TABLE,
        [
            {
                "dataset_id": device.dataset_id,
                "device_id": device.device_id,
                "device_type": device.device_type,
                "vendor": device.vendor,
                "model": device.model,
                "specs": dict(device.specs),
            }
            for device in domain.devices
        ],
    )
    written["session"] = _upsert(
        connection,
        SESSION_TABLE,
        [
            {
                "dataset_id": session.dataset_id,
                "session_id": session.session_id,
                "kind": session.kind.value,
                "protocol_id": session.protocol_id,
                "label": session.label,
                "started_at": session.started_at,
                "ended_at": session.ended_at,
                "venue": session.venue,
            }
            for session in domain.all_sessions
        ],
    )
    written["session_participant"] = _upsert(
        connection,
        SESSION_PARTICIPANT_TABLE,
        [
            {
                "dataset_id": participant.dataset_id,
                "session_id": participant.session_id,
                "subject_id": participant.subject_id,
                "role": participant.role.value,
                "group_label": participant.group_label,
            }
            for participant in domain.participants
        ],
    )
    written["trial"] = _upsert(
        connection,
        TRIAL_TABLE,
        [
            {
                "dataset_id": trial.dataset_id,
                "session_id": trial.session_id,
                "trial_id": trial.trial_id,
                "subject_id": trial.subject_id,
                "parent_trial_id": trial.parent_trial_id,
                "label": trial.label,
                "started_at": trial.started_at,
                "ended_at": trial.ended_at,
            }
            for trial in domain.trials
        ],
    )
    written["clock"] = _upsert(
        connection,
        CLOCK_TABLE,
        [
            {
                "clock_id": clock.clock_id,
                "timebase": clock.timebase.value,
                "frequency_hz": clock.frequency_hz,
                "epoch_utc": clock.epoch_utc,
                "drift_ppm": clock.drift_ppm,
                "rollover_period_s": clock.rollover_period_s,
                "notes": clock.notes,
            }
            for clock in domain.authorities.clocks
        ],
    )
    written["coordinate_frame"] = _upsert(
        connection,
        COORDINATE_FRAME_TABLE,
        [
            {
                "frame_id": frame.frame_id,
                "name": frame.name,
                "kind": frame.kind.value,
                "handedness": frame.handedness.value,
                "x_direction": frame.x_direction.value,
                "y_direction": frame.y_direction.value,
                "z_direction": frame.z_direction.value,
                "origin_description": frame.origin_description,
                "length_unit": frame.length_unit,
                "parent_frame_id": frame.parent_frame_id,
                "description": frame.description,
            }
            for frame in domain.authorities.frames
        ],
    )
    written["synchronization_spec"] = _upsert(
        connection,
        SYNCHRONIZATION_SPEC_TABLE,
        [
            {
                "sync_spec_id": spec.sync_spec_id,
                "method": spec.method.value,
                "reference_clock_id": spec.reference_clock_id,
                "uncertainty_ms": spec.uncertainty_ms,
                "residual_max_abs_ms": spec.residual_max_abs_ms,
                "residual_rms_ms": spec.residual_rms_ms,
                "verified": spec.verified,
                "verified_at": spec.verified_at,
                "evidence_artifact_id": spec.evidence_artifact_id,
                "notes": spec.notes,
            }
            for spec in domain.authorities.synchronizations
        ],
    )
    # Skeleton definitions and their joints precede the pose streams that
    # reference them: a pose stream must never cite an undeclared skeleton, and a
    # landmark_set skeleton persists its absent parent ids as nulls rather than
    # fabricating a tree. The sync converges on the current declaration so a
    # rerun cannot leave a stale definition or stale joints behind.
    written["skeleton_definition"], written["skeleton_joint"] = _sync_skeletons(
        connection, domain.authorities.skeletons
    )
    written["sensor_stream"] = _upsert(
        connection,
        SENSOR_STREAM_TABLE,
        [
            {
                "dataset_id": stream.dataset_id,
                "stream_id": stream.stream_id,
                "session_id": stream.session_id,
                "trial_id": stream.trial_id,
                "subject_id": stream.subject_id,
                "device_id": stream.device_id,
                "modality": stream.modality.value,
                "measurement_class": stream.measurement_class.value,
                "clock_id": stream.clock_id,
                "synchronization_spec_id": stream.synchronization_spec_id,
                "coordinate_frame_id": stream.coordinate_frame_id,
                "skeleton_id": stream.skeleton_id,
                "nominal_sampling_rate_hz": stream.nominal_sampling_rate_hz,
                "si_units": list(stream.si_units),
                "source_unit": stream.source_unit,
                "stream_metadata": dict(stream.stream_metadata),
            }
            for stream in domain.streams
        ],
    )
    # Alignments are persisted only after their endpoints and sync spec exist;
    # the composite foreign keys then prove the dataset-scoped pairing.
    written["sync_alignment"] = _upsert_alignment(connection, _alignment_rows(domain))
    return written


def persist_ingest_run(
    connection,
    *,
    dataset_id: str,
    result: IngestResult,
    domain: ProviderDomain,
    algorithm: AlgorithmSpec,
    source_checksums: tuple[str, ...],
    run_id: str,
    code_git_sha: str | None = None,
) -> tuple[dict[str, int], ProcessingRun]:
    written: dict[str, int] = {}
    written["algorithm_spec"] = _upsert(
        connection,
        ALGORITHM_SPEC_TABLE,
        [
            {
                "algorithm_id": algorithm.algorithm_id,
                "name": algorithm.name,
                "version": algorithm.version,
                "kind": algorithm.kind.value,
                "code_git_sha": algorithm.code_git_sha,
                "parameters": dict(algorithm.parameters),
                "parameters_hash": algorithm.parameters_hash,
                "description": algorithm.description,
                "citation": algorithm.citation,
            }
        ],
    )
    completed_at = datetime.now(UTC)
    run = ProcessingRun(
        run_id=run_id,
        dataset_id=dataset_id,
        algorithm_id=algorithm.algorithm_id,
        status=ProcessingStatus.COMPLETED,
        code_git_sha=code_git_sha,
        completed_at=completed_at,
        inputs=tuple(_processing_inputs(source_checksums)),
        notes=processing_run_notes(
            dataset_id=dataset_id,
            session_id=result.session_id,
            algorithm_id=algorithm.algorithm_id,
        ),
    )
    written["processing_run"] = _update_run(
        connection,
        PROCESSING_RUN_TABLE,
        {
            "run_id": run.run_id,
            "dataset_id": run.dataset_id,
            "algorithm_id": run.algorithm_id,
            "status": run.status.value,
            "code_git_sha": run.code_git_sha,
            "parameters_hash": run.parameters_hash,
            "dagster_run_id": run.dagster_run_id,
            "started_at": completed_at,
            "completed_at": run.completed_at,
            "input_checksums": [item.checksum_sha256 for item in run.inputs],
            "notes": run.notes,
        },
    )
    written["sample_artifact"] = _replace_by_path(
        connection,
        SAMPLE_ARTIFACT_TABLE,
        [
            {
                "artifact_id": f"{stream.stream_id}-{stream.checksum_sha256[:12]}",
                "dataset_id": dataset_id,
                # The artifact belongs to the stream's own session; a provider
                # slice may materialize many sessions (one per laboratory subject).
                "session_id": stream.session_id,
                "stream_id": stream.stream_id,
                "layer": "silver",
                "relative_path": stream.relative_path,
                "format": "parquet",
                "compression": "zstd",
                "row_count": stream.row_count,
                "byte_size": stream.byte_size,
                "checksum_sha256": stream.checksum_sha256,
                "schema_version": stream.schema_version,
                "schema_fingerprint": stream.schema_fingerprint,
                "partition": stream.partition,
                "coordinate_frame_id": stream.coordinate_frame_id,
                "synchronization_spec_id": stream.synchronization_spec_id,
                "created_at": completed_at,
            }
            for stream in result.streams
        ],
        dataset_id=dataset_id,
    )
    processing_artifacts = [
        {
            "artifact_id": f"art-{stream.stream_id}-{stream.checksum_sha256[:12]}",
            "dataset_id": dataset_id,
            "run_id": run_id,
            "artifact_type": f"silver_{stream.modality}",
            "layer": "silver",
            "relative_path": stream.relative_path,
            "checksum_sha256": stream.checksum_sha256,
            "byte_size": stream.byte_size,
            "row_count": stream.row_count,
            "created_at": completed_at,
            "artifact_metadata": {
                "stream_id": stream.stream_id,
                "schema_fingerprint": stream.schema_fingerprint,
                "contract_schema_fingerprint": stream.contract_schema_fingerprint,
            },
        }
        for stream in result.streams
    ]
    processing_artifacts.extend(
        {
            "artifact_id": f"art-quarantine-{artifact['rule']}-{artifact['checksum_sha256'][:12]}",
            "dataset_id": dataset_id,
            "run_id": run_id,
            "artifact_type": f"quarantine_{artifact['rule']}",
            "layer": "quarantine",
            "relative_path": artifact["relative_path"],
            "checksum_sha256": artifact["checksum_sha256"],
            "byte_size": artifact["byte_size"],
            "row_count": artifact["row_count"],
            "created_at": completed_at,
            "artifact_metadata": {"rule": artifact["rule"]},
        }
        for artifact in result.quarantine_artifacts
    )
    written["processing_artifact"] = _replace_by_path(
        connection,
        PROCESSING_ARTIFACT_TABLE,
        processing_artifacts,
        dataset_id=dataset_id,
    )
    issues = _quality_issues(dataset_id, run_id, result)
    connection.execute(QUALITY_ISSUE_TABLE.delete().where(QUALITY_ISSUE_TABLE.c.run_id == run_id))
    written["quality_issue"] = _upsert(connection, QUALITY_ISSUE_TABLE, issues)
    # Source-derived observations are the current materialization of this run:
    # replacing them makes a rerun that removes or quarantines an observation, or
    # that changes a value under an unchanged identity, converge to the current
    # source state instead of preserving stale rows.
    connection.execute(DERIVED_METRIC_TABLE.delete().where(DERIVED_METRIC_TABLE.c.run_id == run_id))
    if result.source_metrics:
        from dynamis.pipeline.source_metrics import persist_source_metrics

        written.update(
            persist_source_metrics(
                connection,
                dataset_id=dataset_id,
                run_id=run_id,
                observations=result.source_metrics,
                input_checksums=source_checksums,
                computed_at=completed_at,
            )
        )
    return written, run


def _processing_inputs(checksums: tuple[str, ...]):
    """Bind a run to its verified Bronze checksums.

    A run must never cite one of its own outputs as an input: if no Bronze
    checksum is available the caller has skipped manifest verification, which is
    a programming error rather than something to paper over.
    """
    from dynamis.contracts import ProcessingInput

    usable = [checksum for checksum in checksums if len(checksum) == 64]
    if not usable:
        raise ValueError(
            "no verified Bronze checksums are available; persist only after "
            "Bronze manifest verification"
        )
    return [
        ProcessingInput(artifact_id=f"bronze-{index}", checksum_sha256=checksum, role="bronze")
        for index, checksum in enumerate(usable)
    ]


def _quality_issues(dataset_id: str, run_id: str, result: IngestResult) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for index, record in enumerate(result.quarantine_records):
        issues.append(
            {
                "issue_id": f"qi-{run_id}-{index:05d}"[:128],
                "dataset_id": dataset_id,
                "run_id": run_id,
                "session_id": record.session_id,
                "stream_id": record.stream_id,
                "subject_id": record.subject_id,
                "trial_id": None,
                "sample_index": None,
                "rule": record.rule,
                "severity": record.severity.value,
                "state": "QUARANTINED",
                "evidence": dict(record.evidence)
                or {"detail": record.detail, "source_record_id": record.source_record_id},
                "detected_at": datetime.now(UTC),
            }
        )
    return issues


def persist_ingest(
    settings: Settings,
    *,
    dataset_id: str,
    version: str,
    domain: ProviderDomain,
    result: IngestResult,
    algorithm: AlgorithmSpec,
    run_id: str,
    code_git_sha: str | None = None,
    engine: Engine | None = None,
) -> PersistSummary:
    """Full control-plane persistence for one ingestion."""
    from dynamis.storage.control_plane import control_plane_engine

    registry = validate_registry()
    source = source_by_id(registry, dataset_id)
    owns_engine = engine is None
    active = engine or control_plane_engine(settings)
    written: dict[str, int] = {}
    try:
        with active.begin() as connection:
            written.update(persist_source(connection, source))
            checksums = persist_bronze_state(
                connection, settings, dataset_id=dataset_id, version=version
            )
            written.update(persist_domain(connection, domain))
            run_written, _run = persist_ingest_run(
                connection,
                dataset_id=dataset_id,
                result=result,
                domain=domain,
                algorithm=algorithm,
                source_checksums=checksums,
                run_id=run_id,
                code_git_sha=code_git_sha,
            )
            written.update(run_written)
    finally:
        if owns_engine:
            active.dispose()
    return PersistSummary(
        dataset_id=dataset_id,
        version=version,
        run_id=run_id,
        rows_written={key: value for key, value in written.items() if value},
    )
