"""Corpus-level tactical materialization shared by Dagster and demo preparation.

Every function reads accepted canonical Silver streams through the control
plane (checksum-verified), runs one pure tactical processor and persists the
result. Nothing here downloads data. Level availability comes from the tactical
capability matrix, never from what happens to be on disk.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import lru_cache
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
from sqlalchemy.engine import Engine

from dynamis.config import Settings, repository_root
from dynamis.processors.corpus import SilverStreamRef, list_silver_streams, load_silver
from dynamis.processors.runtime import ProcessorRunResult, execute_processor
from dynamis.processors.spec import ProcessorResult
from dynamis.processors.tactical_events import process_tactical_event_snapshots
from dynamis.processors.tactical_geometry import process_tactical_geometry
from dynamis.processors.tactical_influence import process_tactical_influence
from dynamis.processors.tactical_shape import process_tactical_shape
from dynamis.processors.tactical_sources import load_tactical_source_authority
from dynamis.processors.tactical_territory import process_tactical_territory

#: Tracking-only tactical processors by capability level.
TRACKING_LEVELS: dict[str, Callable[[pa.Table], ProcessorResult]] = {
    "A": process_tactical_geometry,
    "B": process_tactical_territory,
    "C": process_tactical_influence,
}

#: Series every level must serve for one tracking stream.
LEVEL_SERIES: dict[str, tuple[str, ...]] = {
    "A": ("team_geometry", "interpersonal", "team_relations"),
    "B": ("player_territory", "team_territory"),
    "C": ("team_influence", "player_influence", "influence_grid"),
    "D": ("source_event_snapshots",),
    "V3": (
        "functional_unit_geometry",
        "shape_graph_edges",
        "tactical_triangles",
        "attacker_defender_interactions",
        "source_possession_context",
    ),
}

LEVEL_ALGORITHMS: dict[str, str] = {
    "A": "tactical.team_geometry",
    "B": "tactical.spatial_territory",
    "C": "tactical.arrival_time",
    "D": "tactical.source_event_snapshot",
    "V3": "tactical.matchlab_shape",
}

_CAPABILITY_KEYS = {
    "A": "level_a_geometry",
    "B": "level_b_territory",
    "C": "level_c_influence",
    "D": "level_d_event_linked",
    "V3": "matchlab_v3_functional_units",
}


@lru_cache(maxsize=1)
def _capability_matrix() -> dict[str, Any]:
    path = repository_root() / "sources" / "tactical-capability-matrix.json"
    return json.loads(path.read_text(encoding="utf-8"))


def supported_levels(dataset_id: str) -> tuple[str, ...]:
    """Tactical levels declared supported by the capability authority."""
    payload = _capability_matrix()["datasets"].get(dataset_id)
    if payload is None:
        return ()
    capabilities = payload["capabilities"]
    return tuple(
        level
        for level, key in _CAPABILITY_KEYS.items()
        if str(capabilities.get(key, "unavailable")).startswith("supported")
    )


def event_snapshot_result(
    event_table: pa.Table, tracking_ref: SilverStreamRef, tracking_table: pa.Table
) -> ProcessorResult | None:
    """Level D for one tracking period; ``None`` when the period has no events."""
    period_events = event_table.filter(
        pc.call_function("equal", [event_table["trial_id"], pa.scalar(tracking_ref.trial_id)])
    )
    if period_events.num_rows == 0:
        return None
    return process_tactical_event_snapshots(period_events, tracking_table)


def materialize_tracking_level(
    settings: Settings,
    engine: Engine,
    *,
    dataset_id: str,
    level: str,
    ref: SilverStreamRef,
    table: pa.Table,
    tracking_input: Any,
    code_sha: str | None = None,
) -> ProcessorRunResult:
    """Run and persist one tracking-only tactical level for one stream."""
    result = TRACKING_LEVELS[level](table)
    return execute_processor(
        settings,
        result=result,
        dataset_id=dataset_id,
        inputs=(tracking_input,),
        series_key=ref.stream_id,
        engine=engine,
        code_sha=code_sha,
    )


def materialize_event_level(
    settings: Settings,
    engine: Engine,
    *,
    dataset_id: str,
    ref: SilverStreamRef,
    table: pa.Table,
    tracking_input: Any,
    event_table: pa.Table,
    event_input: Any,
    code_sha: str | None = None,
) -> ProcessorRunResult | None:
    """Run and persist Level D source-event snapshots for one tracking period.

    The series key is the tracking stream id, so the served artifact carries the
    same ``stream_id`` as the geometry/territory series of that period and the
    Field laboratory finds all levels of one stream with one query.
    """
    result = event_snapshot_result(event_table, ref, table)
    if result is None:
        return None
    return execute_processor(
        settings,
        result=result,
        dataset_id=dataset_id,
        inputs=(event_input, tracking_input),
        series_key=ref.stream_id,
        engine=engine,
        code_sha=code_sha,
    )


def materialize_matchlab_v3(
    settings: Settings,
    engine: Engine,
    *,
    dataset_id: str,
    ref: SilverStreamRef,
    table: pa.Table,
    tracking_input: Any,
    code_sha: str | None = None,
) -> ProcessorRunResult:
    """Run source-authorized MatchLab V3 geometry for one canonical stream."""
    source = load_tactical_source_authority(
        settings,
        dataset_id=dataset_id,
        trial_id=ref.trial_id,
        tracking=table,
    )
    result = process_tactical_shape(
        table,
        role_by_player=source.role_by_player,
        attacking_direction_by_team=source.attacking_direction_by_team,
        possession=source.possession,
        role_authority=source.role_authority,
        direction_authority=source.direction_authority,
    )
    return execute_processor(
        settings,
        result=result,
        dataset_id=dataset_id,
        inputs=(*source.inputs, tracking_input),
        series_key=ref.stream_id,
        engine=engine,
        code_sha=code_sha,
    )


def dataset_event_runs(settings: Settings, engine: Engine, *, dataset_id: str) -> dict[str, Any]:
    """Level D over every tracking period of a dataset with one event stream."""
    with engine.connect() as connection:
        event_refs = list_silver_streams(connection, dataset_id=dataset_id, modality="event")
        tracking_refs = list_silver_streams(connection, dataset_id=dataset_id, modality="tracking")
    if len(event_refs) != 1 or not tracking_refs:
        raise ValueError(
            f"{dataset_id}: tactical event processing requires one event stream and "
            "tracking periods"
        )
    event_table, event_input = load_silver(settings, event_refs[0])
    run_ids: list[str] = []
    for ref in tracking_refs:
        table, tracking_input = load_silver(settings, ref)
        run = materialize_event_level(
            settings,
            engine,
            dataset_id=dataset_id,
            ref=ref,
            table=table,
            tracking_input=tracking_input,
            event_table=event_table,
            event_input=event_input,
        )
        if run is not None:
            run_ids.append(run.run_id)
    return {
        "dataset_id": dataset_id,
        "algorithm_id": LEVEL_ALGORITHMS["D"],
        "runs": len(run_ids),
        "run_ids": sorted(run_ids),
        "derived_event_labels": False,
    }


__all__ = [
    "LEVEL_ALGORITHMS",
    "LEVEL_SERIES",
    "TRACKING_LEVELS",
    "dataset_event_runs",
    "event_snapshot_result",
    "materialize_event_level",
    "materialize_matchlab_v3",
    "materialize_tracking_level",
    "supported_levels",
]
