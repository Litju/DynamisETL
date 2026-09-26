"""PostgreSQL reads for the analytical API.

The control plane (schema ``dynamis`` by default) is the scientific/provenance
authority. The published Gold serving schema is read for curated metric serving
when it exists; otherwise the control-plane current-revision selection is served
with an explicit ``source`` marker. No endpoint recomputes science.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from dynamis.gold.build import MART_NAMES
from dynamis.serving.models import (
    AlgorithmView,
    ArtifactRefView,
    DatasetDetail,
    DatasetSummary,
    DatasetVersionView,
    LicenseView,
    MetricCatalogEntry,
    MetricDefinitionView,
    MetricMethodology,
    MetricPage,
    MetricValue,
    ProvenanceEdge,
    ProvenanceGraph,
    ProvenanceNode,
    QualityIssuePage,
    QualityIssueView,
    RightsPolicyView,
    RunView,
    SessionDetail,
    SessionParticipantView,
    SessionSummary,
    SkeletonDisplayConnectionView,
    SourceCapabilityView,
    StreamView,
    SubjectView,
    TrialView,
)

TRIAL_METRICS_MART = "gold_trial_metrics"

MEASUREMENT_CLASS_SEMANTICS: dict[str, str] = {
    "RAW_MEASURED": "Directly measured instrument signal.",
    "SOURCE_DERIVED": "Computed by the source/provider from its own measurements; "
    "a reference, not ground truth.",
    "PIPELINE_DERIVED": "Computed by a versioned DynamisData processor from canonical inputs.",
    "MODEL_ESTIMATED": "Estimated by a provider model; never a raw instrument measurement.",
}

MEASUREMENT_CLASS_NEVER_MEANS: list[str] = [
    "SOURCE_DERIVED is not ground truth.",
    "MODEL_ESTIMATED is not a measurement.",
    "A provider p90 error radius is not a confidence interval or probability.",
    "A rank correlation is not accuracy or validity.",
]


def _source_readiness(availability_state: str, upstream_capabilities: set[str]) -> str:
    if availability_state == "ACQUISITION_FAILED":
        return "UPSTREAM_FAILED"
    return "UPSTREAM_AVAILABLE" if upstream_capabilities else "UPSTREAM_UNAVAILABLE"


def list_source_capabilities(connection: Connection, dataset_id: str) -> list[SourceCapabilityView]:
    """Separate provider-available capability from locally materialized data."""
    entries = (
        connection.execute(
            sa.text(
                """
            SELECT entry_id, external_id, object_kind, availability_state,
                   upstream_capabilities, provider_metadata
            FROM source_catalog_entry
            WHERE dataset = :dataset_id AND object_kind IN ('contest', 'aggregate')
            ORDER BY object_kind, external_id
            """
            ),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .all()
    )
    if not entries:
        return []

    local: dict[str, set[str]] = {str(row["entry_id"]): set() for row in entries}
    modalities = connection.execute(
        sa.text(
            """
            SELECT ctx.source_catalog_entry_id, stream.modality
            FROM session_sport_context AS ctx
            JOIN sensor_stream AS stream
              ON stream.dataset_id = ctx.dataset_id
             AND stream.session_id = ctx.session_id
            JOIN sample_artifact AS artifact
              ON artifact.dataset_id = stream.dataset_id
             AND artifact.stream_id = stream.stream_id
            WHERE ctx.dataset_id = :dataset_id
              AND ctx.source_catalog_entry_id IS NOT NULL
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings()
    modality_capabilities = {
        "tracking": {"TRACKING", "BALL_TRACKING"},
        "pose": {"POSE"},
        "event": {"EVENTS"},
    }
    for row in modalities:
        entry_id = str(row["source_catalog_entry_id"])
        local.setdefault(entry_id, set()).update(modality_capabilities.get(row["modality"], set()))

    aggregate_rows = connection.execute(
        sa.text(
            """
            SELECT artifact_metadata ->> 'source_catalog_entry_id' AS entry_id,
                   artifact_metadata ->> 'aggregate_family' AS family
            FROM processing_artifact
            WHERE dataset_id = :dataset_id
              AND artifact_metadata ? 'source_catalog_entry_id'
            """
        ),
        {"dataset_id": dataset_id},
    ).mappings()
    for row in aggregate_rows:
        local.setdefault(str(row["entry_id"]), set()).add("SEASON_AGGREGATE")

    file_states = {
        str(row["registry_file_key"]): str(row["availability_state"])
        for row in connection.execute(
            sa.text(
                """
                SELECT registry_file_key, availability_state
                FROM source_catalog_entry
                WHERE registry_dataset_id = :dataset_id
                  AND object_kind = 'release_asset'
                  AND registry_file_key IS NOT NULL
                """
            ),
            {"dataset_id": dataset_id},
        ).mappings()
    }
    result: list[SourceCapabilityView] = []
    for row in entries:
        entry_id = str(row["entry_id"])
        upstream = set(map(str, row["upstream_capabilities"] or ()))
        materialized = local.get(entry_id, set())
        metadata = dict(row["provider_metadata"] or {})
        inventory = metadata.get("file_families", {})
        if inventory:
            source_file_states = {
                family: file_states.get(asset["key"], "UPSTREAM_AVAILABLE")
                for family, asset in inventory.items()
            }
            if metadata.get("pose_availability") == "UPSTREAM_UNAVAILABLE":
                source_file_states["pose"] = "UPSTREAM_UNAVAILABLE"
        else:
            key = metadata.get("source_file_key")
            source_file_states = (
                {
                    str(metadata.get("aggregate_family", "aggregate")): file_states.get(
                        key, "UPSTREAM_AVAILABLE"
                    )
                }
                if key
                else {}
            )
        pending = sorted(upstream - materialized)
        readiness = (
            "READY"
            if upstream and not pending
            else "PARTIAL"
            if materialized
            else "NOT_MATERIALIZED"
        )
        result.append(
            SourceCapabilityView(
                entry_id=entry_id,
                external_id=str(row["external_id"]),
                object_kind=str(row["object_kind"]),
                availability_state=str(row["availability_state"]),
                source_readiness=_source_readiness(str(row["availability_state"]), upstream),
                local_readiness=readiness,
                upstream_capabilities=sorted(upstream),
                local_capabilities=sorted(materialized),
                pending_local_capabilities=pending,
                provider_metadata=metadata,
                source_file_states=source_file_states,
            )
        )
    return result


PROVENANCE_FIELDS: list[str] = [
    "measurement_class",
    "metric definition",
    "algorithm_id / algorithm_version",
    "parameters / parameters_hash",
    "processing run (run_id)",
    "code Git SHA",
    "input artifact checksums",
    "source dataset/version",
    "license policy and restrictions",
]


@dataclass(frozen=True, slots=True)
class MetricFilters:
    dataset_id: str | None = None
    session_id: str | None = None
    subject_id: str | None = None
    trial_id: str | None = None
    stream_id: str | None = None
    metric_id: str | None = None
    entity_id: str | None = None

    def parameters(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "session_id": self.session_id,
            "subject_id": self.subject_id,
            "trial_id": self.trial_id,
            "stream_id": self.stream_id,
            "metric_id": self.metric_id,
            "entity_id": self.entity_id,
        }


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def license_notice(fields: dict[str, Any]) -> str:
    """Human-readable rights summary built from the stored policy fields."""
    parts: list[str] = []
    identifier = fields.get("identifier")
    parts.append(str(identifier) if identifier else "license: unclear (local-only)")
    if fields.get("attribution_required"):
        parts.append("attribution required")
    if fields.get("noncommercial_only"):
        parts.append("non-commercial only")
    if fields.get("share_alike"):
        parts.append("share-alike")
    if fields.get("local_only"):
        parts.append("local-only: do not redistribute")
    redistribution = fields.get("redistribution")
    if redistribution:
        parts.append(f"redistribution: {redistribution}")
    for restriction in _list(fields.get("restrictions")):
        parts.append(str(restriction))
    return "; ".join(parts)


def _license_view(row: Any) -> LicenseView:
    fields = {
        "identifier": row["identifier"],
        "attribution_required": row["attribution_required"],
        "noncommercial_only": row["noncommercial_only"],
        "share_alike": row["share_alike"],
        "redistribution": row["redistribution"],
        "local_only": row["local_only"],
        "restrictions": _list(row["restrictions"]),
    }
    return LicenseView(
        policy_id=row["policy_id"],
        identifier=row["identifier"],
        status=row["license_status"],
        attribution_required=row["attribution_required"],
        noncommercial_only=row["noncommercial_only"],
        share_alike=row["share_alike"],
        redistribution=row["redistribution"],
        local_only=row["local_only"],
        restrictions=fields["restrictions"],
        notice=license_notice(fields),
    )


_CONTROL_CURRENT_METRIC_COUNT = """(SELECT count(*) FROM (
        SELECT dm.run_id,
            row_number() OVER (
                PARTITION BY dm.metric_id, COALESCE(dm.subject_id, ''),
                    COALESCE(dm.session_id, ''), COALESCE(dm.trial_id, ''),
                    COALESCE(dm.stream_id, ''), COALESCE(dm.provenance ->> 'entity_id', '')
                ORDER BY dm.computed_at DESC NULLS LAST, dm.run_id DESC
            ) AS revision_rank,
            first_value(dm.run_id) OVER (
                PARTITION BY dm.provenance ->> 'algorithm_id', COALESCE(dm.subject_id, ''),
                    COALESCE(dm.session_id, ''), COALESCE(dm.trial_id, ''),
                    COALESCE(dm.stream_id, '')
                ORDER BY dm.computed_at DESC NULLS LAST, dm.run_id DESC
            ) AS scope_run_id
        FROM derived_metric dm WHERE dm.dataset_id = s.dataset_id
    ) current_metric
    WHERE current_metric.revision_rank = 1
        AND current_metric.run_id = current_metric.scope_run_id)"""


def _dataset_select(connection: Connection, gold_schema: str | None) -> str:
    """Dataset summaries with current-revision metric counts.

    Published Gold is exactly the current revisions, so its mart is counted
    directly; the control-plane rule (the same run-scoped current revision the
    metric endpoint serves) is the fallback before Gold is published.
    """
    if gold_schema is not None and gold_published(connection, gold_schema):
        metric_count = (
            f'(SELECT count(*) FROM "{gold_schema}"."{TRIAL_METRICS_MART}" g '
            "WHERE g.dataset_id = s.dataset_id)"
        )
    else:
        metric_count = _CONTROL_CURRENT_METRIC_COUNT
    return f"""
SELECT
    s.dataset_id, s.name, s.provider, s.domain, s.doi, s.upstream_urls,
    s.v1_role, s.initial_scope, s.adapter_id,
    l.policy_id, l.identifier, l.status AS license_status, l.attribution_required,
    l.noncommercial_only, l.share_alike, l.redistribution, l.local_only, l.restrictions,
    (SELECT json_agg(m.modality ORDER BY m.modality) FROM dataset_source_modality m
        WHERE m.dataset_id = s.dataset_id) AS modalities,
    (SELECT json_agg(DISTINCT st.modality) FROM sensor_stream st
        WHERE st.dataset_id = s.dataset_id) AS ingested_modalities,
    (SELECT count(*) FROM dataset_version v WHERE v.dataset_id = s.dataset_id) AS version_count,
    (SELECT count(*) FROM "session" se WHERE se.dataset_id = s.dataset_id) AS session_count,
    (SELECT count(*) FROM subject su WHERE su.dataset_id = s.dataset_id) AS subject_count,
    (SELECT count(*) FROM trial t WHERE t.dataset_id = s.dataset_id) AS trial_count,
    (SELECT count(*) FROM sensor_stream st WHERE st.dataset_id = s.dataset_id) AS stream_count,
    {metric_count} AS metric_count,
    (SELECT count(*) FROM quality_issue q WHERE q.dataset_id = s.dataset_id) AS quality_issue_count
FROM dataset_source s
JOIN license_policy l ON l.policy_id = s.license_policy_id
"""


def _dataset_summary(row: Any) -> DatasetSummary:
    return DatasetSummary(
        dataset_id=row["dataset_id"],
        name=row["name"],
        provider=row["provider"],
        domain=row["domain"],
        doi=row["doi"],
        upstream_urls=[str(item) for item in _list(row["upstream_urls"])],
        modalities=[str(item) for item in _list(row["modalities"])],
        ingested_modalities=sorted(str(item) for item in _list(row.get("ingested_modalities"))),
        license=_license_view(row),
        version_count=int(row["version_count"]),
        session_count=int(row["session_count"]),
        subject_count=int(row["subject_count"]),
        trial_count=int(row["trial_count"]),
        stream_count=int(row["stream_count"]),
        metric_count=int(row["metric_count"]),
        quality_issue_count=int(row["quality_issue_count"]),
    )


def list_datasets(connection: Connection, gold_schema: str | None = None) -> list[DatasetSummary]:
    query = _dataset_select(connection, gold_schema) + " ORDER BY s.dataset_id"
    rows = connection.execute(sa.text(query)).mappings().all()
    return [_dataset_summary(row) for row in rows]


def dataset_detail(
    connection: Connection, dataset_id: str, gold_schema: str | None = None
) -> DatasetDetail | None:
    row = (
        connection.execute(
            sa.text(_dataset_select(connection, gold_schema) + " WHERE s.dataset_id = :dataset_id"),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    versions = (
        connection.execute(
            sa.text(
                "SELECT version, release_date, upstream_url, citation, retrieval_status, "
                "retrieved_at FROM dataset_version "
                "WHERE dataset_id = :dataset_id ORDER BY version"
            ),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .all()
    )
    summary = _dataset_summary(row)
    return DatasetDetail(
        **summary.model_dump(),
        versions=[
            DatasetVersionView(
                version=item["version"],
                release_date=_iso(item["release_date"]),
                upstream_url=item["upstream_url"],
                citation=item["citation"],
                retrieval_status=item["retrieval_status"],
                retrieved_at=_iso(item["retrieved_at"]),
            )
            for item in versions
        ],
        v1_role=str(row["v1_role"]),
        initial_scope=str(row["initial_scope"]),
        adapter_id=str(row["adapter_id"]),
    )


def list_subjects(connection: Connection, dataset_id: str) -> list[SubjectView]:
    rows = (
        connection.execute(
            sa.text(
                "SELECT subject_id, sex, cohort FROM subject WHERE dataset_id = :dataset_id "
                "ORDER BY subject_id"
            ),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .all()
    )
    return [
        SubjectView(subject_id=row["subject_id"], sex=row["sex"], cohort=row["cohort"])
        for row in rows
    ]


def list_sessions(connection: Connection, dataset_id: str) -> list[SessionSummary]:
    rows = (
        connection.execute(
            sa.text(
                """SELECT se.session_id, se.kind, se.label, se.started_at, se.ended_at,
            (SELECT count(*) FROM session_participant p WHERE p.dataset_id = se.dataset_id
                AND p.session_id = se.session_id) AS participant_count,
            (SELECT count(*) FROM trial t WHERE t.dataset_id = se.dataset_id
                AND t.session_id = se.session_id) AS trial_count,
            (SELECT count(*) FROM sensor_stream st WHERE st.dataset_id = se.dataset_id
                AND st.session_id = se.session_id) AS stream_count
            FROM "session" se WHERE se.dataset_id = :dataset_id
            ORDER BY se.session_id"""
            ),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .all()
    )
    return [
        SessionSummary(
            session_id=row["session_id"],
            kind=row["kind"],
            label=row["label"],
            started_at=_iso(row["started_at"]),
            ended_at=_iso(row["ended_at"]),
            participant_count=int(row["participant_count"]),
            trial_count=int(row["trial_count"]),
            stream_count=int(row["stream_count"]),
        )
        for row in rows
    ]


def _skeleton_authorities(
    connection: Connection, skeleton_ids: set[str]
) -> dict[str, tuple[str, list[str], list[SkeletonDisplayConnectionView]]]:
    """Read persisted skeleton display topology separately from parentage."""
    authorities: dict[str, tuple[str, list[str], list[SkeletonDisplayConnectionView]]] = {}
    for skeleton_id in sorted(skeleton_ids):
        if not skeleton_id:
            continue
        definition = (
            connection.execute(
                sa.text(
                    "SELECT topology, display_connections FROM skeleton_definition "
                    "WHERE skeleton_id = :skeleton_id"
                ),
                {"skeleton_id": skeleton_id},
            )
            .mappings()
            .first()
        )
        if definition is None:
            continue
        joints = (
            connection.execute(
                sa.text(
                    "SELECT joint_id, joint_name FROM skeleton_joint "
                    "WHERE skeleton_id = :skeleton_id ORDER BY joint_id"
                ),
                {"skeleton_id": skeleton_id},
            )
            .mappings()
            .all()
        )
        names_by_id = {int(row["joint_id"]): str(row["joint_name"]) for row in joints}
        connections: list[SkeletonDisplayConnectionView] = []
        for item in _list(definition["display_connections"]):
            if not isinstance(item, dict):
                continue
            start = item.get("start_joint_name")
            end = item.get("end_joint_name")
            if not isinstance(start, str) or not isinstance(end, str):
                start_id = item.get("start_joint_id")
                end_id = item.get("end_joint_id")
                start = names_by_id.get(start_id) if isinstance(start_id, int) else None
                end = names_by_id.get(end_id) if isinstance(end_id, int) else None
            if isinstance(start, str) and isinstance(end, str):
                connections.append(
                    SkeletonDisplayConnectionView(
                        start_joint_name=start,
                        end_joint_name=end,
                    )
                )
        authorities[skeleton_id] = (
            str(definition["topology"]),
            [str(row["joint_name"]) for row in joints],
            connections,
        )
    return authorities


def session_detail(
    connection: Connection, dataset_id: str, session_id: str
) -> SessionDetail | None:
    session = (
        connection.execute(
            sa.text(
                """SELECT se.session_id, se.kind, se.label, se.started_at, se.ended_at,
                (SELECT count(*) FROM session_participant p WHERE p.dataset_id = se.dataset_id
                    AND p.session_id = se.session_id) AS participant_count,
                (SELECT count(*) FROM trial t WHERE t.dataset_id = se.dataset_id
                    AND t.session_id = se.session_id) AS trial_count,
                (SELECT count(*) FROM sensor_stream st WHERE st.dataset_id = se.dataset_id
                    AND st.session_id = se.session_id) AS stream_count
                FROM "session" se
                WHERE se.dataset_id = :dataset_id AND se.session_id = :session_id"""
            ),
            {"dataset_id": dataset_id, "session_id": session_id},
        )
        .mappings()
        .first()
    )
    if session is None:
        return None
    participants = (
        connection.execute(
            sa.text(
                "SELECT p.subject_id, p.role, p.group_label, s.cohort, s.notes "
                "FROM session_participant p "
                "LEFT JOIN subject s "
                "ON s.dataset_id = p.dataset_id AND s.subject_id = p.subject_id "
                "WHERE p.dataset_id = :dataset_id AND p.session_id = :session_id "
                "ORDER BY p.subject_id"
            ),
            {"dataset_id": dataset_id, "session_id": session_id},
        )
        .mappings()
        .all()
    )
    trials = (
        connection.execute(
            sa.text(
                "SELECT trial_id, subject_id, parent_trial_id, label, started_at, ended_at "
                "FROM trial WHERE dataset_id = :dataset_id AND session_id = :session_id "
                "ORDER BY trial_id"
            ),
            {"dataset_id": dataset_id, "session_id": session_id},
        )
        .mappings()
        .all()
    )
    streams = (
        connection.execute(
            sa.text(
                """SELECT st.stream_id, st.modality, st.measurement_class, st.subject_id,
            st.trial_id, st.device_id, st.nominal_sampling_rate_hz, st.si_units,
            st.source_unit, st.coordinate_frame_id, st.synchronization_spec_id,
            st.clock_id, st.skeleton_id, st.stream_metadata,
            COALESCE((SELECT sum(a.row_count) FROM sample_artifact a
                WHERE a.dataset_id = st.dataset_id AND a.stream_id = st.stream_id), 0)
                AS sample_row_count,
            COALESCE((SELECT array_agg(a.artifact_id ORDER BY a.artifact_id)
                FROM sample_artifact a WHERE a.dataset_id = st.dataset_id
                AND a.stream_id = st.stream_id), ARRAY[]::text[]) AS artifact_ids
            FROM sensor_stream st
            WHERE st.dataset_id = :dataset_id AND st.session_id = :session_id
            ORDER BY st.stream_id"""
            ),
            {"dataset_id": dataset_id, "session_id": session_id},
        )
        .mappings()
        .all()
    )
    skeletons = _skeleton_authorities(
        connection,
        {str(row["skeleton_id"]) for row in streams if row["skeleton_id"] is not None},
    )
    return SessionDetail(
        dataset_id=dataset_id,
        session=SessionSummary(
            session_id=session["session_id"],
            kind=session["kind"],
            label=session["label"],
            started_at=_iso(session["started_at"]),
            ended_at=_iso(session["ended_at"]),
            participant_count=int(session["participant_count"]),
            trial_count=int(session["trial_count"]),
            stream_count=int(session["stream_count"]),
        ),
        participants=[
            SessionParticipantView(
                subject_id=row["subject_id"],
                role=row["role"],
                group_label=row["group_label"],
                cohort=row["cohort"],
                notes=row["notes"],
            )
            for row in participants
        ],
        trials=[
            TrialView(
                trial_id=row["trial_id"],
                subject_id=row["subject_id"],
                parent_trial_id=row["parent_trial_id"],
                label=row["label"],
                started_at=_iso(row["started_at"]),
                ended_at=_iso(row["ended_at"]),
            )
            for row in trials
        ],
        streams=[
            StreamView(
                stream_id=row["stream_id"],
                modality=row["modality"],
                measurement_class=row["measurement_class"],
                subject_id=row["subject_id"],
                trial_id=row["trial_id"],
                device_id=row["device_id"],
                nominal_sampling_rate_hz=row["nominal_sampling_rate_hz"],
                si_units=[str(item) for item in _list(row["si_units"])],
                source_unit=row["source_unit"],
                coordinate_frame_id=row["coordinate_frame_id"],
                synchronization_spec_id=row["synchronization_spec_id"],
                clock_id=row["clock_id"],
                skeleton_id=row["skeleton_id"],
                skeleton_topology=(
                    skeletons.get(str(row["skeleton_id"]), (None, [], []))[0]
                    if row["skeleton_id"] is not None
                    else None
                ),
                skeleton_joint_names=(
                    skeletons.get(str(row["skeleton_id"]), (None, [], []))[1]
                    if row["skeleton_id"] is not None
                    else []
                ),
                skeleton_display_connections=(
                    skeletons.get(str(row["skeleton_id"]), (None, [], []))[2]
                    if row["skeleton_id"] is not None
                    else []
                ),
                pitch_dimensions_m=(row.get("stream_metadata") or {}).get("pitch_dimensions_m"),
                sample_artifact_ids=[str(item) for item in _list(row["artifact_ids"])],
                sample_row_count=int(row["sample_row_count"]),
            )
            for row in streams
        ],
    )


def gold_published(connection: Connection, gold_schema: str) -> bool:
    relation = connection.execute(
        sa.text("SELECT to_regclass(:relation)"),
        {"relation": f'"{gold_schema}"."{TRIAL_METRICS_MART}"'},
    ).scalar_one()
    return relation is not None


def _metric_filters_sql(
    filters: MetricFilters, *, gold: bool = False
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    parameters = filters.parameters()
    for name, value in parameters.items():
        if value is None:
            continue
        column = "entity_id" if name == "entity_id" else name
        if name == "entity_id":
            clauses.append(
                "COALESCE(entity_id, '') = :entity_id"
                if gold
                else "COALESCE(provenance ->> 'entity_id', '') = :entity_id"
            )
        else:
            clauses.append(f"{column} = :{name}")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, {name: value for name, value in parameters.items() if value is not None}


_CONTROL_METRIC_SELECT = """
WITH ranked AS (
    SELECT
        m.derived_metric_id, m.dataset_id, m.metric_id, m.subject_id, m.session_id,
        m.trial_id, m.stream_id, m.si_unit, m.measurement_class, m.value_num,
        m.value_json, m.computed_at, m.run_id, m.input_checksums, m.provenance,
        d.name AS metric_name, d.description AS metric_description, d.value_kind,
        m.provenance ->> 'algorithm_id' AS algorithm_id,
        m.provenance ->> 'algorithm_version' AS algorithm_version,
        m.provenance ->> 'parameters_hash' AS parameters_hash,
        m.provenance ->> 'code_git_sha' AS code_git_sha,
        COALESCE(m.provenance ->> 'entity_id', '') AS entity_key,
        row_number() OVER (
            PARTITION BY
                m.dataset_id, m.metric_id, COALESCE(m.subject_id, ''), COALESCE(m.session_id, ''),
                COALESCE(m.trial_id, ''), COALESCE(m.stream_id, ''),
                COALESCE(m.provenance ->> 'entity_id', '')
            ORDER BY m.computed_at DESC NULLS LAST, m.run_id DESC
        ) AS revision_rank,
        first_value(m.run_id) OVER (
            PARTITION BY
                m.dataset_id, m.provenance ->> 'algorithm_id', COALESCE(m.subject_id, ''),
                COALESCE(m.session_id, ''), COALESCE(m.trial_id, ''), COALESCE(m.stream_id, '')
            ORDER BY m.computed_at DESC NULLS LAST, m.run_id DESC
        ) AS scope_run_id
    FROM derived_metric m
    LEFT JOIN metric_definition d ON d.metric_id = m.metric_id
),
current_revision AS (
    SELECT * FROM ranked WHERE revision_rank = 1 AND run_id = scope_run_id
)
"""


def query_metrics(
    connection: Connection,
    *,
    gold_schema: str,
    filters: MetricFilters,
    limit: int,
    offset: int,
) -> MetricPage:
    """Current-revision scalar metrics, from Gold serving when published."""
    is_gold = gold_published(connection, gold_schema)
    where, parameters = _metric_filters_sql(filters, gold=is_gold)
    if is_gold:
        mart = f'"{gold_schema}"."{TRIAL_METRICS_MART}"'
        total = connection.execute(
            sa.text(f"SELECT count(*) FROM {mart}{where}"), parameters
        ).scalar_one()
        rows = (
            connection.execute(
                sa.text(
                    f"SELECT * FROM {mart}{where} "
                    "ORDER BY dataset_id, metric_id, COALESCE(session_id, ''), "
                    "COALESCE(subject_id, ''), COALESCE(trial_id, ''), COALESCE(stream_id, ''), "
                    "COALESCE(entity_id, '') LIMIT :limit OFFSET :offset"
                ),
                {**parameters, "limit": limit, "offset": offset},
            )
            .mappings()
            .all()
        )
        return MetricPage(
            source="gold",
            total=int(total),
            limit=limit,
            offset=offset,
            rows=[
                MetricValue(
                    derived_metric_id=row["derived_metric_id"],
                    dataset_id=row["dataset_id"],
                    metric_id=row["metric_id"],
                    metric_name=row.get("metric_name"),
                    metric_description=row.get("metric_description"),
                    si_unit=row["si_unit"],
                    measurement_class=row["measurement_class"],
                    value_kind="scalar",
                    value_num=row["value_num"],
                    value_json=None,
                    subject_id=row.get("subject_id"),
                    session_id=row.get("session_id"),
                    trial_id=row.get("trial_id"),
                    stream_id=row.get("stream_id"),
                    entity_id=row.get("entity_id"),
                    algorithm_id=row.get("algorithm_id"),
                    algorithm_version=row.get("algorithm_version"),
                    parameters_hash=row.get("parameters_hash"),
                    code_git_sha=row.get("code_git_sha"),
                    run_id=row["run_id"],
                    computed_at=_iso(row.get("computed_at")),
                    provenance={},
                )
                for row in rows
            ],
        )
    total = connection.execute(
        sa.text(f"{_CONTROL_METRIC_SELECT} SELECT count(*) FROM current_revision{where}"),
        parameters,
    ).scalar_one()
    rows = (
        connection.execute(
            sa.text(
                f"{_CONTROL_METRIC_SELECT} SELECT * FROM current_revision{where} "
                "ORDER BY dataset_id, metric_id, COALESCE(session_id, ''), "
                "COALESCE(subject_id, ''), COALESCE(trial_id, ''), COALESCE(stream_id, ''), "
                "entity_key LIMIT :limit OFFSET :offset"
            ),
            {**parameters, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    return MetricPage(
        source="control_plane",
        total=int(total),
        limit=limit,
        offset=offset,
        rows=[
            MetricValue(
                derived_metric_id=row["derived_metric_id"],
                dataset_id=row["dataset_id"],
                metric_id=row["metric_id"],
                metric_name=row["metric_name"],
                metric_description=row["metric_description"],
                si_unit=row["si_unit"],
                measurement_class=row["measurement_class"],
                value_kind=row["value_kind"] or "scalar",
                value_num=row["value_num"],
                value_json=row["value_json"],
                subject_id=row["subject_id"],
                session_id=row["session_id"],
                trial_id=row["trial_id"],
                stream_id=row["stream_id"],
                entity_id=(row["entity_key"] or None),
                algorithm_id=row["algorithm_id"],
                algorithm_version=row["algorithm_version"],
                parameters_hash=row["parameters_hash"],
                code_git_sha=row["code_git_sha"],
                run_id=row["run_id"],
                computed_at=_iso(row["computed_at"]),
                provenance=dict(row["provenance"] or {}),
            )
            for row in rows
        ],
    )


def list_metric_definitions(connection: Connection) -> list[MetricCatalogEntry]:
    """Registered metric definitions with the datasets that actually serve them.

    Discovery needs the vocabulary, not the values: a reader choosing what to
    compare or inspect should not have to page through 77k derived rows to find
    out which metric ids exist. The served-dataset list comes from the derived
    rows so the catalog never offers a metric nothing has computed.
    """
    rows = (
        connection.execute(
            sa.text(
                """SELECT d.metric_id, d.name, d.si_unit, d.measurement_class, d.value_kind,
                    d.description, d.algorithm_id,
                    coalesce(s.dataset_ids, '[]'::json) AS dataset_ids,
                    coalesce(c.value_count, 0) AS value_count
                FROM metric_definition d
                LEFT JOIN (
                    -- Distinct pairs first, then aggregate. A DISTINCT inside
                    -- the aggregate sorts every row of each group; this form is
                    -- an index-only scan of (metric_id, dataset_id).
                    SELECT metric_id, json_agg(dataset_id ORDER BY dataset_id) AS dataset_ids
                    FROM (SELECT DISTINCT metric_id, dataset_id FROM derived_metric) pairs
                    GROUP BY metric_id
                ) s ON s.metric_id = d.metric_id
                LEFT JOIN (
                    SELECT metric_id, count(*) AS value_count
                    FROM derived_metric GROUP BY metric_id
                ) c ON c.metric_id = d.metric_id
                ORDER BY d.metric_id"""
            )
        )
        .mappings()
        .all()
    )
    return [
        MetricCatalogEntry(
            metric_id=row["metric_id"],
            name=row["name"],
            si_unit=row["si_unit"],
            measurement_class=row["measurement_class"],
            value_kind=row["value_kind"],
            description=row["description"],
            algorithm_id=row["algorithm_id"],
            dataset_ids=[str(item) for item in _list(row["dataset_ids"])],
            value_count=int(row["value_count"]),
        )
        for row in rows
    ]


def metric_methodology(connection: Connection, metric_id: str) -> MetricMethodology | None:
    row = (
        connection.execute(
            sa.text(
                """SELECT metric_id, name, si_unit, measurement_class, value_kind,
                description, algorithm_id FROM metric_definition WHERE metric_id = :metric_id"""
            ),
            {"metric_id": metric_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    algorithm = None
    if row["algorithm_id"] is not None:
        algorithm = _algorithm_view(connection, str(row["algorithm_id"]))
    return MetricMethodology(
        metric=MetricDefinitionView(
            metric_id=row["metric_id"],
            name=row["name"],
            si_unit=row["si_unit"],
            measurement_class=row["measurement_class"],
            value_kind=row["value_kind"],
            description=row["description"],
            algorithm_id=row["algorithm_id"],
        ),
        algorithm=algorithm,
        measurement_class_semantics=MEASUREMENT_CLASS_SEMANTICS.get(
            row["measurement_class"], "Unclassified measurement class."
        ),
        measurement_class_never_means=MEASUREMENT_CLASS_NEVER_MEANS,
        provenance_fields=PROVENANCE_FIELDS,
    )


def _algorithm_view(connection: Connection, algorithm_id: str) -> AlgorithmView | None:
    row = (
        connection.execute(
            sa.text(
                """SELECT algorithm_id, name, version, kind, code_git_sha, parameters_hash,
                parameters, description, citation FROM algorithm_spec
                WHERE algorithm_id = :algorithm_id"""
            ),
            {"algorithm_id": algorithm_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return AlgorithmView(
        algorithm_id=row["algorithm_id"],
        name=row["name"],
        version=row["version"],
        kind=row["kind"],
        code_git_sha=row["code_git_sha"],
        parameters_hash=row["parameters_hash"],
        parameters=dict(row["parameters"] or {}),
        description=row["description"],
        citation=row["citation"],
    )


def provenance_graph(connection: Connection, derived_metric_id: str) -> ProvenanceGraph | None:
    row = (
        connection.execute(
            sa.text(
                """SELECT m.derived_metric_id, m.dataset_id, m.metric_id, m.session_id,
                m.trial_id, m.stream_id, m.subject_id, m.si_unit, m.measurement_class,
                m.value_num, m.computed_at, m.run_id, m.input_checksums, m.provenance,
                d.name AS metric_name, r.algorithm_id, r.code_git_sha, r.parameters_hash,
                r.input_checksums AS run_input_checksums, r.status AS run_status,
                r.started_at, r.completed_at
                FROM derived_metric m
                JOIN processing_run r ON r.run_id = m.run_id
                LEFT JOIN metric_definition d ON d.metric_id = m.metric_id
                WHERE m.derived_metric_id = :derived_metric_id"""
            ),
            {"derived_metric_id": derived_metric_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    nodes: list[ProvenanceNode] = []
    edges: list[ProvenanceEdge] = []

    def add_node(node: ProvenanceNode) -> None:
        if all(existing.id != node.id for existing in nodes):
            nodes.append(node)

    dataset_id = str(row["dataset_id"])
    dataset_row = (
        connection.execute(
            sa.text(
                "SELECT name, provider, domain FROM dataset_source WHERE dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        )
        .mappings()
        .first()
    )
    add_node(
        ProvenanceNode(
            id=f"dataset:{dataset_id}",
            kind="dataset",
            label=str(dataset_row["name"]) if dataset_row else dataset_id,
            details={
                "dataset_id": dataset_id,
                "provider": dataset_row["provider"] if dataset_row else None,
                "domain": dataset_row["domain"] if dataset_row else None,
            },
        )
    )

    algorithm_id = row["algorithm_id"]
    if algorithm_id is not None:
        algorithm = _algorithm_view(connection, str(algorithm_id))
        add_node(
            ProvenanceNode(
                id=f"algorithm:{algorithm_id}",
                kind="algorithm",
                label=f"{algorithm.name}@{algorithm.version}" if algorithm else str(algorithm_id),
                details={
                    "algorithm_id": algorithm_id,
                    "version": algorithm.version if algorithm else None,
                    "kind": algorithm.kind if algorithm else None,
                    "parameters_hash": row["parameters_hash"],
                    "code_git_sha": row["code_git_sha"],
                    "parameters": algorithm.parameters if algorithm else {},
                },
            )
        )
    run_id = str(row["run_id"])
    add_node(
        ProvenanceNode(
            id=f"run:{run_id}",
            kind="processing_run",
            label=run_id,
            status=row["run_status"],
            details={
                "started_at": _iso(row["started_at"]),
                "completed_at": _iso(row["completed_at"]),
                "code_git_sha": row["code_git_sha"],
                "parameters_hash": row["parameters_hash"],
            },
        )
    )

    checksums = [str(item) for item in _list(row["run_input_checksums"])]
    for checksum in checksums:
        artifact = _artifact_by_checksum(connection, checksum)
        if artifact is None:
            add_node(
                ProvenanceNode(
                    id=f"checksum:{checksum}",
                    kind="input_checksum",
                    label=checksum[:16],
                    details={"checksum_sha256": checksum, "resolved": False},
                )
            )
            continue
        node_kind = "silver_artifact" if artifact.artifact_kind == "sample" else "derived_artifact"
        add_node(
            ProvenanceNode(
                id=f"artifact:{artifact.artifact_id}",
                kind=node_kind,
                label=artifact.artifact_id,
                measurement_class=artifact.measurement_class,
                details={
                    "relative_path": artifact.relative_path,
                    "checksum_sha256": artifact.checksum_sha256,
                    "row_count": artifact.row_count,
                    "stream_id": artifact.stream_id,
                    "layer": artifact.layer,
                },
            )
        )

    stream_id = row["stream_id"]
    if stream_id is not None:
        stream = (
            connection.execute(
                sa.text(
                    "SELECT modality, measurement_class, clock_id, synchronization_spec_id, "
                    "coordinate_frame_id, skeleton_id FROM sensor_stream "
                    "WHERE dataset_id = :dataset_id AND stream_id = :stream_id"
                ),
                {"dataset_id": dataset_id, "stream_id": stream_id},
            )
            .mappings()
            .first()
        )
        add_node(
            ProvenanceNode(
                id=f"stream:{stream_id}",
                kind="sensor_stream",
                label=str(stream_id),
                measurement_class=stream["measurement_class"] if stream else None,
                details=dict(stream) if stream else {},
            )
        )

    metric_id = str(row["metric_id"])
    add_node(
        ProvenanceNode(
            id=f"metric:{metric_id}",
            kind="metric_definition",
            label=str(row["metric_name"]) if row["metric_name"] else metric_id,
            measurement_class=row["measurement_class"],
            details={"metric_id": metric_id, "si_unit": row["si_unit"]},
        )
    )
    add_node(
        ProvenanceNode(
            id=f"derived:{derived_metric_id}",
            kind="derived_metric",
            label=derived_metric_id,
            measurement_class=row["measurement_class"],
            details={
                "value_num": row["value_num"],
                "si_unit": row["si_unit"],
                "computed_at": _iso(row["computed_at"]),
                "session_id": row["session_id"],
                "subject_id": row["subject_id"],
                "trial_id": row["trial_id"],
                "stream_id": row["stream_id"],
            },
        )
    )
    add_node(
        ProvenanceNode(
            id=f"gold:{derived_metric_id}",
            kind="gold_row",
            label=f"gold_trial_metrics · {derived_metric_id}",
            measurement_class=row["measurement_class"],
            details={"mart": TRIAL_METRICS_MART},
        )
    )

    def link(source: str, target: str, label: str) -> None:
        edges.append(
            ProvenanceEdge(
                id=f"{source}->{target}",
                source=source,
                target=target,
                label=label,
            )
        )

    ordered_artifacts = [
        node
        for node in nodes
        if node.kind in {"silver_artifact", "derived_artifact", "input_checksum"}
    ]
    for artifact in ordered_artifacts:
        link(f"dataset:{dataset_id}", artifact.id, "input artifact")
        if stream_id is not None:
            link(artifact.id, f"stream:{stream_id}", "canonicalizes to")
    if stream_id is not None:
        link(f"stream:{stream_id}", f"metric:{metric_id}", "input stream")
    else:
        link(f"dataset:{dataset_id}", f"metric:{metric_id}", "input dataset")
    if algorithm_id is not None:
        link(f"metric:{metric_id}", f"algorithm:{algorithm_id}", "computed by")
        link(f"algorithm:{algorithm_id}", f"run:{run_id}", "executed as")
    else:
        link(f"metric:{metric_id}", f"run:{run_id}", "recorded in")
    for artifact in ordered_artifacts:
        link(artifact.id, f"run:{run_id}", "input checksum")
    link(f"run:{run_id}", f"derived:{derived_metric_id}", "results in")
    link(f"derived:{derived_metric_id}", f"gold:{derived_metric_id}", "served as")
    return ProvenanceGraph(
        derived_metric_id=derived_metric_id,
        nodes=nodes,
        edges=edges,
        provenance=dict(row["provenance"] or {}),
        lineage_note=(
            "Selected result lineage only. Scientific values are never recomputed from "
            "the graph; it exposes the exact stored provenance chain."
        ),
    )


def _artifact_by_checksum(connection: Connection, checksum: str) -> ArtifactRefView | None:
    sample = (
        connection.execute(
            sa.text(
                """SELECT a.artifact_id, a.dataset_id, a.stream_id, a.layer, a.relative_path,
                a.format, a.compression, a.checksum_sha256, a.row_count, a.byte_size,
                a.coordinate_frame_id, a.synchronization_spec_id,
                st.modality, st.measurement_class, st.si_units
                FROM sample_artifact a
                LEFT JOIN sensor_stream st ON st.dataset_id = a.dataset_id
                    AND st.stream_id = a.stream_id
                WHERE a.checksum_sha256 = :checksum ORDER BY a.artifact_id LIMIT 1"""
            ),
            {"checksum": checksum},
        )
        .mappings()
        .first()
    )
    if sample is not None:
        return _artifact_view(sample, kind="sample")
    processing = (
        connection.execute(
            sa.text(
                """SELECT p.artifact_id, p.dataset_id, p.layer, p.relative_path,
                p.checksum_sha256, p.row_count, p.byte_size, p.artifact_type,
                p.artifact_metadata,
                COALESCE(
                    p.artifact_metadata->>'stream_id',
                    p.artifact_metadata->>'series_key'
                ) AS stream_id,
                p.artifact_metadata->>'measurement_class' AS measurement_class,
                p.artifact_metadata->>'coordinate_frame_id' AS coordinate_frame_id,
                p.artifact_metadata->>'input_measurement_class' AS input_measurement_class,
                p.artifact_metadata->>'algorithm_version' AS algorithm_version,
                p.artifact_metadata->>'parameters_hash' AS parameters_hash,
                r.algorithm_id, r.run_id
                FROM processing_artifact p
                JOIN processing_run r ON r.run_id = p.run_id
                WHERE p.checksum_sha256 = :checksum ORDER BY p.artifact_id LIMIT 1"""
            ),
            {"checksum": checksum},
        )
        .mappings()
        .first()
    )
    if processing is not None:
        return _artifact_view(processing, kind="processing")
    return None


def _artifact_view(row: Any, *, kind: Literal["sample", "processing"]) -> ArtifactRefView:
    measurement_class = row.get("measurement_class")
    if kind == "processing" and measurement_class is None:
        measurement_class = "PIPELINE_DERIVED"
    return ArtifactRefView(
        artifact_id=row["artifact_id"],
        dataset_id=row["dataset_id"],
        stream_id=row.get("stream_id"),
        layer=row["layer"],
        relative_path=row["relative_path"],
        format=str(row.get("format") or "parquet"),
        compression=row.get("compression"),
        checksum_sha256=row["checksum_sha256"],
        row_count=int(row["row_count"] or 0),
        byte_size=row.get("byte_size"),
        artifact_kind=kind,
        modality=row.get("modality"),
        measurement_class=measurement_class,
        si_units=[str(item) for item in _list(row.get("si_units"))],
        coordinate_frame_id=row.get("coordinate_frame_id"),
        synchronization_spec_id=row.get("synchronization_spec_id"),
        algorithm_id=row.get("algorithm_id"),
        algorithm_version=row.get("algorithm_version"),
        parameters_hash=row.get("parameters_hash"),
        run_id=row.get("run_id"),
        artifact_metadata=dict(row.get("artifact_metadata") or {}),
    )


def resolve_artifact(connection: Connection, artifact_id: str) -> ArtifactRefView | None:
    return _artifact_by_id(connection, artifact_id)


def _artifact_by_id(connection: Connection, artifact_id: str) -> ArtifactRefView | None:
    sample = (
        connection.execute(
            sa.text(
                """SELECT a.artifact_id, a.dataset_id, a.stream_id, a.layer, a.relative_path,
                a.format, a.compression, a.checksum_sha256, a.row_count, a.byte_size,
                a.coordinate_frame_id, a.synchronization_spec_id,
                st.modality, st.measurement_class, st.si_units
                FROM sample_artifact a
                LEFT JOIN sensor_stream st ON st.dataset_id = a.dataset_id
                    AND st.stream_id = a.stream_id
                WHERE a.artifact_id = :artifact_id"""
            ),
            {"artifact_id": artifact_id},
        )
        .mappings()
        .first()
    )
    if sample is not None:
        return _artifact_view(sample, kind="sample")
    processing = (
        connection.execute(
            sa.text(
                """SELECT p.artifact_id, p.dataset_id, p.layer, p.relative_path,
                p.checksum_sha256, p.row_count, p.byte_size, p.artifact_type,
                p.artifact_metadata,
                COALESCE(
                    p.artifact_metadata->>'stream_id',
                    p.artifact_metadata->>'series_key'
                ) AS stream_id,
                p.artifact_metadata->>'measurement_class' AS measurement_class,
                p.artifact_metadata->>'coordinate_frame_id' AS coordinate_frame_id,
                p.artifact_metadata->>'input_measurement_class' AS input_measurement_class,
                p.artifact_metadata->>'algorithm_version' AS algorithm_version,
                p.artifact_metadata->>'parameters_hash' AS parameters_hash,
                r.algorithm_id, r.run_id
                FROM processing_artifact p
                JOIN processing_run r ON r.run_id = p.run_id
                WHERE p.artifact_id = :artifact_id"""
            ),
            {"artifact_id": artifact_id},
        )
        .mappings()
        .first()
    )
    if processing is not None:
        return _artifact_view(processing, kind="processing")
    return None


def list_tactical_artifacts(
    connection: Connection,
    *,
    dataset_id: str,
    session_id: str | None = None,
    stream_id: str | None = None,
    series_name: str | None = None,
) -> list[ArtifactRefView]:
    """List persisted tactical series without exposing non-tactical artifacts."""
    clauses = [
        "p.dataset_id = :dataset_id",
        "p.artifact_metadata->>'tactical_level' IS NOT NULL",
    ]
    parameters: dict[str, Any] = {"dataset_id": dataset_id}
    if session_id is not None:
        clauses.append("p.artifact_metadata->>'session_id' = :session_id")
        parameters["session_id"] = session_id
    if stream_id is not None:
        clauses.append("p.artifact_metadata->>'stream_id' = :stream_id")
        parameters["stream_id"] = stream_id
    if series_name is not None:
        clauses.append("p.artifact_metadata->>'series_name' = :series_name")
        parameters["series_name"] = series_name
    # Only the current completed run of each algorithm over a session stream is
    # served: a rerun (new code revision or parameters) supersedes the previous
    # run's series instead of listing both, so a series name resolves to exactly
    # one artifact.
    query = f"""
        WITH candidates AS (
            SELECT p.artifact_id, p.dataset_id, p.layer, p.relative_path,
                p.checksum_sha256, p.row_count, p.byte_size, p.artifact_type,
                p.artifact_metadata, p.artifact_metadata->>'stream_id' AS stream_id,
                p.artifact_metadata->>'measurement_class' AS measurement_class,
                p.artifact_metadata->>'coordinate_frame_id' AS coordinate_frame_id,
                p.artifact_metadata->>'algorithm_version' AS algorithm_version,
                p.artifact_metadata->>'parameters_hash' AS parameters_hash,
                r.algorithm_id, r.run_id,
                first_value(r.run_id) OVER (
                    PARTITION BY r.algorithm_id,
                        COALESCE(p.artifact_metadata->>'session_id', ''),
                        COALESCE(p.artifact_metadata->>'stream_id', '')
                    ORDER BY r.completed_at DESC NULLS LAST, r.run_id DESC
                ) AS current_run_id
            FROM processing_artifact p
            JOIN processing_run r ON r.run_id = p.run_id
            WHERE r.status = 'completed' AND {" AND ".join(clauses)}
        )
        SELECT * FROM candidates
        WHERE run_id = current_run_id
        ORDER BY artifact_metadata->>'series_name', artifact_id
    """
    rows = connection.execute(sa.text(query), parameters).mappings().all()
    return [_artifact_view(row, kind="processing") for row in rows]


def list_processing_artifacts(
    connection: Connection,
    *,
    dataset_id: str,
    session_id: str | None = None,
    stream_id: str | None = None,
    algorithm_id: str | None = None,
    series_name: str | None = None,
) -> list[ArtifactRefView]:
    """List current processor series for one dataset/session/stream context."""
    clauses = ["p.dataset_id = :dataset_id"]
    parameters: dict[str, Any] = {"dataset_id": dataset_id}
    if session_id is not None:
        clauses.append("COALESCE(p.artifact_metadata->>'session_id', s.session_id) = :session_id")
        parameters["session_id"] = session_id
    if stream_id is not None:
        clauses.append(
            "COALESCE(p.artifact_metadata->>'stream_id', p.artifact_metadata->>'series_key') "
            "= :stream_id"
        )
        parameters["stream_id"] = stream_id
    if algorithm_id is not None:
        clauses.append("r.algorithm_id = :algorithm_id")
        parameters["algorithm_id"] = algorithm_id
    series_filter = ""
    if series_name is not None:
        series_filter = "AND artifact_metadata->>'series_name' = :series_name"
        parameters["series_name"] = series_name
    query = f"""
        WITH candidates AS (
            SELECT p.artifact_id, p.dataset_id, p.layer, p.relative_path,
                p.checksum_sha256, p.row_count, p.byte_size, p.artifact_type,
                p.artifact_metadata,
                COALESCE(
                    p.artifact_metadata->>'stream_id',
                    p.artifact_metadata->>'series_key'
                ) AS stream_id,
                p.artifact_metadata->>'measurement_class' AS measurement_class,
                p.artifact_metadata->>'coordinate_frame_id' AS coordinate_frame_id,
                p.artifact_metadata->>'algorithm_version' AS algorithm_version,
                p.artifact_metadata->>'parameters_hash' AS parameters_hash,
                r.algorithm_id, r.run_id,
                first_value(r.run_id) OVER (
                    PARTITION BY r.algorithm_id,
                        COALESCE(p.artifact_metadata->>'session_id', s.session_id, ''),
                        COALESCE(
                            p.artifact_metadata->>'stream_id',
                            p.artifact_metadata->>'series_key',
                            ''
                        )
                    ORDER BY r.completed_at DESC NULLS LAST, r.run_id DESC
                ) AS current_run_id
            FROM processing_artifact p
            JOIN processing_run r ON r.run_id = p.run_id
            LEFT JOIN sensor_stream s ON s.dataset_id = p.dataset_id
                AND s.stream_id = COALESCE(
                    p.artifact_metadata->>'stream_id',
                    p.artifact_metadata->>'series_key'
                )
            WHERE r.status = 'completed' AND {" AND ".join(clauses)}
        )
        SELECT * FROM candidates
        WHERE run_id = current_run_id
            {series_filter}
        ORDER BY algorithm_id, artifact_metadata->>'series_name', artifact_id
    """
    rows = connection.execute(sa.text(query), parameters).mappings().all()
    return [_artifact_view(row, kind="processing") for row in rows]


def list_quality_issues(
    connection: Connection,
    *,
    dataset_id: str | None,
    session_id: str | None,
    severity: str | None,
    limit: int,
    offset: int,
) -> QualityIssuePage:
    clauses: list[str] = []
    parameters: dict[str, Any] = {}
    if dataset_id is not None:
        clauses.append("dataset_id = :dataset_id")
        parameters["dataset_id"] = dataset_id
    if session_id is not None:
        clauses.append("session_id = :session_id")
        parameters["session_id"] = session_id
    if severity is not None:
        clauses.append("severity = :severity")
        parameters["severity"] = severity
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    total = connection.execute(
        sa.text(f"SELECT count(*) FROM quality_issue{where}"), parameters
    ).scalar_one()
    rows = (
        connection.execute(
            sa.text(
                f"SELECT * FROM quality_issue{where} "
                "ORDER BY detected_at DESC NULLS LAST, issue_id LIMIT :limit OFFSET :offset"
            ),
            {**parameters, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    return QualityIssuePage(
        total=int(total),
        limit=limit,
        offset=offset,
        rows=[
            QualityIssueView(
                issue_id=row["issue_id"],
                dataset_id=row["dataset_id"],
                run_id=row["run_id"],
                session_id=row["session_id"],
                stream_id=row["stream_id"],
                subject_id=row["subject_id"],
                trial_id=row["trial_id"],
                sample_index=row["sample_index"],
                rule=row["rule"],
                severity=row["severity"],
                state=row["state"],
                evidence=dict(row["evidence"] or {}),
                detected_at=_iso(row["detected_at"]),
            )
            for row in rows
        ],
    )


def list_runs(
    connection: Connection,
    *,
    dataset_id: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[RunView]]:
    parameters: dict[str, Any] = {}
    where = ""
    if dataset_id is not None:
        where = " WHERE r.dataset_id = :dataset_id"
        parameters["dataset_id"] = dataset_id
    total = connection.execute(
        sa.text(f"SELECT count(*) FROM processing_run r{where}"), parameters
    ).scalar_one()
    rows = (
        connection.execute(
            sa.text(
                f"""SELECT r.run_id, r.dataset_id, r.algorithm_id, r.status, r.code_git_sha,
            r.parameters_hash, r.started_at, r.completed_at, r.input_checksums, r.notes,
            a.name AS algorithm_name, a.version AS algorithm_version, a.kind,
            (SELECT count(*) FROM derived_metric m WHERE m.run_id = r.run_id) AS metric_count,
            (SELECT count(*) FROM processing_artifact p WHERE p.run_id = r.run_id)
                AS artifact_count
            FROM processing_run r
            LEFT JOIN algorithm_spec a ON a.algorithm_id = r.algorithm_id{where}
            ORDER BY r.started_at DESC NULLS LAST, r.run_id LIMIT :limit OFFSET :offset"""
            ),
            {**parameters, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    return int(total), [
        RunView(
            run_id=row["run_id"],
            dataset_id=row["dataset_id"],
            algorithm_id=row["algorithm_id"],
            algorithm_name=row["algorithm_name"],
            algorithm_version=row["algorithm_version"],
            kind=row["kind"],
            status=row["status"],
            code_git_sha=row["code_git_sha"],
            parameters_hash=row["parameters_hash"],
            started_at=_iso(row["started_at"]),
            completed_at=_iso(row["completed_at"]),
            input_checksums=[str(item) for item in _list(row["input_checksums"])],
            metric_count=int(row["metric_count"]),
            artifact_count=int(row["artifact_count"]),
            notes=row["notes"],
        )
        for row in rows
    ]


def list_licenses(connection: Connection) -> list[RightsPolicyView]:
    """Rights view: every policy with the datasets governed by it."""
    rows = (
        connection.execute(
            sa.text(
                """SELECT l.policy_id, l.identifier, l.status AS license_status,
            l.attribution_required, l.noncommercial_only, l.share_alike,
            l.redistribution, l.local_only, l.restrictions,
            COALESCE((SELECT json_agg(s.dataset_id ORDER BY s.dataset_id)
                FROM dataset_source s WHERE s.license_policy_id = l.policy_id), '[]'::json)
                AS dataset_ids
            FROM license_policy l ORDER BY l.policy_id"""
            )
        )
        .mappings()
        .all()
    )
    return [
        RightsPolicyView(
            license=_license_view(row),
            dataset_ids=[str(item) for item in _list(row["dataset_ids"])],
        )
        for row in rows
    ]


def serving_status(connection: Connection, *, gold_schema: str, db_schema: str) -> dict[str, Any]:
    published = gold_published(connection, gold_schema)
    counts = (
        connection.execute(
            sa.text(
                "SELECT (SELECT count(*) FROM dataset_source) AS dataset_count, "
                "(SELECT count(*) FROM derived_metric) AS metric_count, "
                "(SELECT count(*) FROM processing_run) AS run_count, "
                "(SELECT count(*) FROM quality_issue) AS quality_issue_count"
            )
        )
        .mappings()
        .one()
    )
    return {
        "database": "ok",
        "db_schema": db_schema,
        "gold_schema": gold_schema,
        "gold_published": published,
        "dataset_count": int(counts["dataset_count"]),
        "metric_count": int(counts["metric_count"]),
        "run_count": int(counts["run_count"]),
        "quality_issue_count": int(counts["quality_issue_count"]),
    }


def mart_names() -> tuple[str, ...]:
    return MART_NAMES
