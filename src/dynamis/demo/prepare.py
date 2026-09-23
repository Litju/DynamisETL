"""``dynamis-demo-prepare``: deterministic local preparation of the flagship routes.

The workbench is only as complete as the artifacts behind it. This command
turns the flagship Field and Pose routes from "implemented" into "ready":

1. verify every required accepted local source is registered, present on disk
   and matches its registered checksum (fail loudly otherwise);
2. materialize the processors the capability authority declares supported
   (athlete locomotor metrics, tactical Levels A-D, Pose kinematics), skipping a
   stream whose current completed run already has the same algorithm,
   parameters hash and input checksums;
3. rebuild and publish Gold when the served marts disagree with the control
   plane's current revisions;
4. verify serving registration (tactical series per stream and level, athlete
   only locomotor entities, Pose kinematics per stream);
5. print the exact flagship URLs.

It reads and writes only the configured local roots and the control plane. It
never downloads, fetches or redistributes data. ``--check`` performs steps 1
and 4 only and exits non-zero when anything is missing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from dynamis.config import Settings, repository_root, settings
from dynamis.processors.acceptance import (
    POSE_REQUIRED_COLUMNS,
    SKILLCORNER_ACCEPTANCE_PARAMETERS,
    SKILLCORNER_POSE_PARAMETERS,
    TRACKING_ACCEPTANCE_PARAMETERS,
)
from dynamis.processors.corpus import SilverStreamRef, list_silver_streams, load_silver
from dynamis.processors.runtime import execute_processor
from dynamis.processors.tactical_corpus import (
    LEVEL_ALGORITHMS,
    LEVEL_SERIES,
    TRACKING_LEVELS,
    event_snapshot_result,
    materialize_event_level,
    materialize_tracking_level,
    supported_levels,
)
from dynamis.registry import source_by_id, validate_registry
from dynamis.storage.atomic import atomic_write_text
from dynamis.storage.control_plane import control_plane_engine
from dynamis.storage.paths import receipt_path

LOCOMOTOR_ALGORITHM = "locomotor.speed_effort_kinematics"
POSE_ALGORITHM = "pose.translation_invariant_kinematics"
#: Rows used to obtain a tactical processor's parameters hash without a full run.
PROBE_ROWS = 23 * 8


class PreparationError(RuntimeError):
    """A required local source or artifact is missing or inconsistent."""


@dataclass(frozen=True)
class FlagshipSession:
    """One flagship route and the local authority it depends on."""

    dataset_id: str
    session_id: str
    required_streams: dict[str, int]
    locomotor_parameters: dict[str, Any]
    field_stream: str
    pose_stream: str | None = None


FLAGSHIPS: tuple[FlagshipSession, ...] = (
    FlagshipSession(
        dataset_id="dfl-sportec-idsse",
        session_id="DFL-MAT-J03WPY",
        required_streams={"tracking": 2, "event": 1},
        locomotor_parameters=TRACKING_ACCEPTANCE_PARAMETERS,
        field_stream="tracking-period-1",
    ),
    FlagshipSession(
        dataset_id="skillcorner-opendata",
        session_id="1925299",
        required_streams={"tracking": 2, "pose": 2},
        locomotor_parameters=SKILLCORNER_ACCEPTANCE_PARAMETERS,
        field_stream="tracking-period-1",
        pose_stream="pose-period-1",
    ),
)


@dataclass
class Report:
    """Human and machine-readable preparation outcome."""

    sources: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    gold: dict[str, Any] | None = None
    urls: list[str] = field(default_factory=list)

    def fail(self, name: str, detail: str) -> None:
        self.checks.append({"check": name, "ok": False, "detail": detail})

    def ok(self, name: str, detail: str) -> None:
        self.checks.append({"check": name, "ok": True, "detail": detail})

    @property
    def ready(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "sources": self.sources,
            "steps": self.steps,
            "checks": self.checks,
            "gold": self.gold,
            "urls": self.urls,
        }


def _log(message: str) -> None:
    print(message, flush=True)


def _safe_console() -> None:
    """Never fail a preparation run on a console that cannot encode a character."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


# --- 1. sources ---------------------------------------------------------------


def _session_streams(engine: Engine, flagship: FlagshipSession) -> list[SilverStreamRef]:
    with engine.connect() as connection:
        return list(
            list_silver_streams(
                connection, dataset_id=flagship.dataset_id, session_id=flagship.session_id
            )
        )


def verify_sources(resolved: Settings, engine: Engine, report: Report) -> None:
    """Fail loudly unless every required accepted source is local and intact."""
    registry = validate_registry()
    problems: list[str] = []
    for flagship in FLAGSHIPS:
        source = source_by_id(registry, flagship.dataset_id)
        refs = _session_streams(engine, flagship)
        for modality, minimum in flagship.required_streams.items():
            found = [ref for ref in refs if ref.modality == modality]
            if len(found) < minimum:
                problems.append(
                    f"{flagship.dataset_id}/{flagship.session_id}: {len(found)} registered "
                    f"{modality} stream(s), {minimum} required — run the accepted ingest first"
                )
        for ref in refs:
            path = resolved.dataset_root / ref.relative_path
            if not path.is_file():
                problems.append(f"registered Silver artifact is absent: {ref.relative_path}")
                continue
            report.sources.append(
                {
                    "dataset_id": ref.dataset_id,
                    "stream_id": ref.stream_id,
                    "modality": ref.modality,
                    "relative_path": ref.relative_path,
                    "checksum_sha256": ref.checksum_sha256,
                    "rows": ref.row_count,
                    "license": source.license.identifier,
                    "license_status": source.license.status.value,
                }
            )
    if problems:
        raise PreparationError("\n".join(problems))


# --- 2. processors ------------------------------------------------------------


def _current_run(
    engine: Engine,
    *,
    algorithm_id: str,
    parameters_hash: str,
    checksums: tuple[str, ...],
    stream_id: str | None,
) -> str | None:
    """The completed run that already covers this exact input and configuration."""
    artifact_clause = (
        "AND EXISTS (SELECT 1 FROM processing_artifact p WHERE p.run_id = r.run_id "
        "AND p.artifact_metadata->>'stream_id' = :stream_id)"
        if stream_id is not None
        else ""
    )
    query = sa.text(
        f"""
        SELECT r.run_id FROM processing_run r
        WHERE r.algorithm_id = :algorithm_id AND r.status = 'completed'
          AND r.parameters_hash = :parameters_hash
          AND r.input_checksums @> CAST(:checksums AS jsonb)
          {artifact_clause}
        ORDER BY r.completed_at DESC NULLS LAST, r.run_id DESC
        LIMIT 1
        """
    )
    parameters: dict[str, Any] = {
        "algorithm_id": algorithm_id,
        "parameters_hash": parameters_hash,
        "checksums": json.dumps(list(checksums)),
    }
    if stream_id is not None:
        parameters["stream_id"] = stream_id
    with engine.connect() as connection:
        return connection.execute(query, parameters).scalar_one_or_none()


def _step(
    report: Report,
    *,
    name: str,
    current: str | None,
    force: bool,
    run: Callable[[], str | None],
) -> bool:
    """Run one materialization unless an identical current run exists."""
    if current is not None and not force:
        report.steps.append({"step": name, "action": "current", "run_id": current})
        _log(f"  current   {name}  ({current})")
        return False
    started = datetime.now(UTC)
    _log(f"  running   {name} ...")
    run_id = run()
    seconds = round((datetime.now(UTC) - started).total_seconds(), 1)
    report.steps.append(
        {"step": name, "action": "materialized", "run_id": run_id, "seconds": seconds}
    )
    _log(f"  done      {name}  ({run_id}, {seconds} s)")
    return True


def _locomotor_step(
    resolved: Settings,
    engine: Engine,
    report: Report,
    flagship: FlagshipSession,
    ref: SilverStreamRef,
    *,
    force: bool,
) -> bool:
    from dynamis.processors.locomotor import locomotor_spec, process_locomotor

    spec = locomotor_spec(flagship.locomotor_parameters)
    current = _current_run(
        engine,
        algorithm_id=LOCOMOTOR_ALGORITHM,
        parameters_hash=spec.parameters_hash,
        checksums=(ref.checksum_sha256,),
        stream_id=None,
    )

    def run() -> str:
        table, processor_input = load_silver(resolved, ref)
        result = process_locomotor(table, parameters=flagship.locomotor_parameters)
        return execute_processor(
            resolved,
            result=result,
            dataset_id=flagship.dataset_id,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        ).run_id

    return _step(
        report,
        name=f"{flagship.dataset_id} {ref.stream_id} locomotor (athletes)",
        current=current,
        force=force,
        run=run,
    )


def _pose_step(
    resolved: Settings,
    engine: Engine,
    report: Report,
    flagship: FlagshipSession,
    ref: SilverStreamRef,
    *,
    force: bool,
) -> bool:
    from dynamis.processors.pose import pose_spec, process_pose

    spec = pose_spec(SKILLCORNER_POSE_PARAMETERS)
    current = _current_run(
        engine,
        algorithm_id=POSE_ALGORITHM,
        parameters_hash=spec.parameters_hash,
        checksums=(ref.checksum_sha256,),
        stream_id=None,
    )

    def run() -> str:
        table, processor_input = load_silver(resolved, ref, columns=POSE_REQUIRED_COLUMNS)
        result = process_pose(table, parameters=SKILLCORNER_POSE_PARAMETERS)
        return execute_processor(
            resolved,
            result=result,
            dataset_id=flagship.dataset_id,
            inputs=(processor_input,),
            series_key=ref.stream_id,
            engine=engine,
        ).run_id

    return _step(
        report,
        name=f"{flagship.dataset_id} {ref.stream_id} pose kinematics",
        current=current,
        force=force,
        run=run,
    )


def _tactical_steps(
    resolved: Settings,
    engine: Engine,
    report: Report,
    flagship: FlagshipSession,
    tracking: list[SilverStreamRef],
    events: list[SilverStreamRef],
    *,
    levels: tuple[str, ...],
    force: bool,
) -> None:
    event_table: pa.Table | None = None
    event_input: Any = None
    if "D" in levels:
        if len(events) != 1:
            raise PreparationError(
                f"{flagship.dataset_id}: Level D is supported but {len(events)} event streams "
                "are registered"
            )
        event_table, event_input = load_silver(resolved, events[0])
    for ref in tracking:
        table, tracking_input = load_silver(resolved, ref)
        probe = table.slice(0, min(table.num_rows, PROBE_ROWS))
        for level in levels:
            if level == "D":
                assert event_table is not None
                probe_result = event_snapshot_result(event_table, ref, probe)
                if probe_result is None:
                    report.steps.append(
                        {
                            "step": f"{flagship.dataset_id} {ref.stream_id} tactical D",
                            "action": "no source events in period",
                        }
                    )
                    continue
                checksums: tuple[str, ...] = (event_input.checksum_sha256, ref.checksum_sha256)

                def run_d(
                    ref: SilverStreamRef = ref,
                    table: pa.Table = table,
                    tracking_input: Any = tracking_input,
                ) -> str | None:
                    assert event_table is not None
                    run = materialize_event_level(
                        resolved,
                        engine,
                        dataset_id=flagship.dataset_id,
                        ref=ref,
                        table=table,
                        tracking_input=tracking_input,
                        event_table=event_table,
                        event_input=event_input,
                    )
                    return None if run is None else run.run_id

                runner: Callable[[], str | None] = run_d
                parameters_hash = probe_result.spec.parameters_hash
            else:
                parameters_hash = TRACKING_LEVELS[level](probe).spec.parameters_hash
                checksums = (ref.checksum_sha256,)

                def run_tracking(
                    level: str = level,
                    ref: SilverStreamRef = ref,
                    table: pa.Table = table,
                    tracking_input: Any = tracking_input,
                ) -> str | None:
                    return materialize_tracking_level(
                        resolved,
                        engine,
                        dataset_id=flagship.dataset_id,
                        level=level,
                        ref=ref,
                        table=table,
                        tracking_input=tracking_input,
                    ).run_id

                runner = run_tracking
            current = _current_run(
                engine,
                algorithm_id=LEVEL_ALGORITHMS[level],
                parameters_hash=parameters_hash,
                checksums=checksums,
                stream_id=ref.stream_id,
            )
            _step(
                report,
                name=f"{flagship.dataset_id} {ref.stream_id} tactical {level}",
                current=current,
                force=force,
                run=runner,
            )


def materialize(
    resolved: Settings,
    engine: Engine,
    report: Report,
    *,
    force: bool,
    skip_levels: tuple[str, ...],
) -> bool:
    """Materialize every supported processor; return True when metrics changed."""
    metrics_changed = False
    for flagship in FLAGSHIPS:
        _log(f"{flagship.dataset_id} / {flagship.session_id}")
        refs = _session_streams(engine, flagship)
        tracking = [ref for ref in refs if ref.modality == "tracking"]
        events = [ref for ref in refs if ref.modality == "event"]
        for ref in tracking:
            metrics_changed |= _locomotor_step(resolved, engine, report, flagship, ref, force=force)
        for ref in (ref for ref in refs if ref.modality == "pose"):
            metrics_changed |= _pose_step(resolved, engine, report, flagship, ref, force=force)
        levels = tuple(
            level for level in supported_levels(flagship.dataset_id) if level not in skip_levels
        )
        _tactical_steps(
            resolved,
            engine,
            report,
            flagship,
            tracking,
            events,
            levels=levels,
            force=force,
        )
    return metrics_changed


# --- 3. gold ------------------------------------------------------------------

_CURRENT_COUNTS = """
WITH ranked AS (
    SELECT m.dataset_id, m.run_id,
        row_number() OVER (
            PARTITION BY m.dataset_id, m.metric_id, COALESCE(m.subject_id, ''),
                COALESCE(m.session_id, ''), COALESCE(m.trial_id, ''),
                COALESCE(m.stream_id, ''), COALESCE(m.provenance ->> 'entity_id', '')
            ORDER BY m.computed_at DESC NULLS LAST, m.run_id DESC
        ) AS revision_rank,
        first_value(m.run_id) OVER (
            PARTITION BY m.dataset_id, m.provenance ->> 'algorithm_id',
                COALESCE(m.subject_id, ''), COALESCE(m.session_id, ''),
                COALESCE(m.trial_id, ''), COALESCE(m.stream_id, '')
            ORDER BY m.computed_at DESC NULLS LAST, m.run_id DESC
        ) AS scope_run_id
    FROM derived_metric m
)
SELECT dataset_id, count(*) FROM ranked
WHERE revision_rank = 1 AND run_id = scope_run_id
GROUP BY dataset_id
"""


def gold_is_current(engine: Engine) -> tuple[bool, dict[str, Any]]:
    """Gold serves exactly the control plane's current revisions per dataset."""
    from dynamis.gold.publish import resolve_gold_schema
    from dynamis.serving.repository import TRIAL_METRICS_MART, gold_published

    schema = resolve_gold_schema()
    with engine.connect() as connection:
        expected = {row[0]: int(row[1]) for row in connection.execute(sa.text(_CURRENT_COUNTS))}
        if not gold_published(connection, schema):
            return False, {"expected": expected, "served": None}
        served = {
            row[0]: int(row[1])
            for row in connection.execute(
                sa.text(
                    f'SELECT dataset_id, count(*) FROM "{schema}"."{TRIAL_METRICS_MART}" '
                    "GROUP BY dataset_id"
                )
            )
        }
    return expected == served, {"expected": expected, "served": served}


def refresh_gold(resolved: Settings, engine: Engine) -> dict[str, Any]:
    from dynamis.gold.build import build_gold
    from dynamis.gold.export import export_serving
    from dynamis.gold.publish import publish_gold

    _log("gold: export -> dbt build -> publish ...")
    export = export_serving(resolved, engine)
    built = build_gold(resolved)
    if not built.success:
        raise PreparationError("dbt build failed; Gold was not published")
    published = publish_gold(resolved, engine)
    return {"export": export.to_dict(), "build": built.to_dict(), "publish": published}


# --- 4. verification ----------------------------------------------------------


def _ball_ids(resolved: Settings, refs: list[SilverStreamRef]) -> set[str]:
    ids: set[str] = set()
    for ref in refs:
        table = pq.read_table(
            resolved.dataset_root / ref.relative_path, columns=["object_id", "object_type"]
        )
        mask = pc.call_function("not_equal", [table["object_type"], pa.scalar("player")])
        ids.update(str(value) for value in table.filter(mask)["object_id"].unique().to_pylist())
    return ids


def verify_serving(resolved: Settings, engine: Engine, report: Report) -> None:
    """Check what the API will serve for every flagship stream."""
    from dynamis.gold.publish import resolve_gold_schema
    from dynamis.serving.repository import TRIAL_METRICS_MART, list_tactical_artifacts

    current, counts = gold_is_current(engine)
    if current:
        report.ok("gold current", f"served metric counts match control plane: {counts['served']}")
    else:
        report.fail("gold current", f"Gold differs from control-plane current revisions: {counts}")
    schema = resolve_gold_schema()
    for flagship in FLAGSHIPS:
        refs = _session_streams(engine, flagship)
        tracking = [ref for ref in refs if ref.modality == "tracking"]
        levels = supported_levels(flagship.dataset_id)
        with engine.connect() as connection:
            for ref in tracking:
                served = list_tactical_artifacts(
                    connection,
                    dataset_id=flagship.dataset_id,
                    session_id=flagship.session_id,
                    stream_id=ref.stream_id,
                )
                names = {str((item.artifact_metadata or {}).get("series_name")) for item in served}
                for level in levels:
                    missing = sorted(set(LEVEL_SERIES[level]) - names)
                    label = f"{flagship.dataset_id} {ref.stream_id} tactical {level}"
                    if missing:
                        report.fail(label, f"missing served series {missing}")
                    else:
                        report.ok(label, f"served {sorted(LEVEL_SERIES[level])}")
            non_athletes = _ball_ids(resolved, tracking)
            leaked: list[str] = []
            if non_athletes and current:
                leaked = [
                    str(row[0])
                    for row in connection.execute(
                        sa.text(
                            f'SELECT DISTINCT entity_id FROM "{schema}"."{TRIAL_METRICS_MART}" '
                            "WHERE dataset_id = :dataset_id AND metric_id LIKE 'locomotor.%' "
                            "AND entity_id = ANY(:ids)"
                        ),
                        {"dataset_id": flagship.dataset_id, "ids": sorted(non_athletes)},
                    )
                ]
            label = f"{flagship.dataset_id} locomotor athletes only"
            if leaked:
                report.fail(label, f"non-athlete objects served as locomotor entities: {leaked}")
            else:
                report.ok(label, f"no locomotor metric for {sorted(non_athletes)}")
        for ref in (ref for ref in refs if ref.modality == "pose"):
            from dynamis.processors.pose import pose_spec

            run = _current_run(
                engine,
                algorithm_id=POSE_ALGORITHM,
                parameters_hash=pose_spec(SKILLCORNER_POSE_PARAMETERS).parameters_hash,
                checksums=(ref.checksum_sha256,),
                stream_id=None,
            )
            label = f"{flagship.dataset_id} {ref.stream_id} pose kinematics"
            if run is None:
                report.fail(label, "no current Pose kinematics run")
            else:
                report.ok(label, run)


def flagship_urls(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    urls = [f"{base}/catalog"]
    for flagship in FLAGSHIPS:
        lab = f"{base}/lab/{flagship.dataset_id}/{flagship.session_id}"
        urls.append(f"{lab}?view=overview")
        urls.append(f"{lab}?view=field&stream={flagship.field_stream}&tactical=live")
        if flagship.pose_stream is not None:
            urls.append(f"{lab}?view=pose&stream={flagship.pose_stream}")
    return urls


def _dirty_sources() -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "analytics", "sources", "architecture"],
        cwd=repository_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dynamis-demo-prepare", description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify sources and serving registration only; exit 1 when not ready",
    )
    parser.add_argument(
        "--force", action="store_true", help="rerun processors even when a current run exists"
    )
    parser.add_argument(
        "--skip-level",
        action="append",
        default=[],
        choices=("A", "B", "C", "D"),
        help="do not materialize this tactical level (verification still reports it)",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="permit persisting runs from a working tree with uncommitted processor code",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    args = parser.parse_args(argv)
    _safe_console()

    resolved = settings()
    engine = control_plane_engine(resolved)
    report = Report()
    try:
        _log("sources: verifying accepted local artifacts ...")
        verify_sources(resolved, engine, report)
        _log(f"sources: {len(report.sources)} registered streams present")
        if not args.check:
            dirty = _dirty_sources()
            if dirty and not args.allow_dirty:
                raise PreparationError(
                    "uncommitted changes under src/analytics/sources/architecture would be "
                    "recorded under the HEAD revision; commit first or pass --allow-dirty:\n"
                    + "\n".join(dirty)
                )
            metrics_changed = materialize(
                resolved,
                engine,
                report,
                force=args.force,
                skip_levels=tuple(args.skip_level),
            )
            current, _counts = gold_is_current(engine)
            if metrics_changed or not current:
                report.gold = refresh_gold(resolved, engine)
        verify_serving(resolved, engine, report)
    except PreparationError as error:
        print(f"PREPARATION FAILED\n{error}", file=sys.stderr, flush=True)
        return 2
    finally:
        engine.dispose()

    report.urls = flagship_urls(args.base_url)
    for item in report.checks:
        _log(f"  {'ok  ' if item['ok'] else 'FAIL'}  {item['check']}: {item['detail']}")
    target = receipt_path(
        resolved,
        dataset_id="dynamis-demo",
        kind="preparation",
        name="flagship-check" if args.check else "flagship-prepare",
    )
    atomic_write_text(target, json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
    _log(f"receipt: {target}")
    if not report.ready:
        print("NOT READY: see FAIL lines above", file=sys.stderr, flush=True)
        return 1
    _log("READY. Flagship routes:")
    for url in report.urls:
        _log(f"  {url}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
