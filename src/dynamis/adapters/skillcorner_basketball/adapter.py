"""Provider identities, periods and clock/spatial authorities for ACB games."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from dynamis.adapters.skillcorner_basketball import authorities
from dynamis.adapters.skillcorner_basketball.catalog import build_game_domain
from dynamis.adapters.skillcorner_basketball.tracking import (
    BasketballTrackingCanonicalizer,
    FrameClockSummary,
)
from dynamis.contracts import (
    AlgorithmKind,
    AlgorithmSpec,
    MeasurementClass,
    Modality,
    SensorStream,
    Trial,
)
from dynamis.contracts.sports import ContestPeriod, PeriodKind, SportsEntityKind
from dynamis.pipeline.streams import SourceAuthorities


def adapter_algorithm_spec() -> AlgorithmSpec:
    return AlgorithmSpec(
        algorithm_id="skillcorner_basketball.spatial_canonicalization",
        name="SkillCorner basketball tracking and event canonicalization",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Canonicalizes source 25 Hz player/ball positions, indexes every source frame, "
            "converts source feet to SI metres through an explicit transform, and preserves "
            "Dynamic Events in the V4 event envelope. The source origin and axes are not "
            "normalized; empty dead-time frames receive no position rows. Event links use "
            "exact source frames or clocks and require a unique target; no nearest-frame "
            "interpolation is performed."
        ),
    )


def materialized_domain(
    *,
    corpus: dict[str, Any],
    catalog_item: dict[str, Any],
    frame_clock: FrameClockSummary,
    tracking: BasketballTrackingCanonicalizer,
):
    base = build_game_domain(corpus, catalog_item)
    contest = base.sports_contexts[0].contest
    periods: list[ContestPeriod] = []
    trials: list[Trial] = []
    for number, summary in sorted(frame_clock.periods.items()):
        kind = PeriodKind.QUARTER if number <= 4 else PeriodKind.OVERTIME
        label = f"Q{number}" if number <= 4 else f"OT{number - 4}"
        periods.append(
            ContestPeriod(
                contest_period_id=f"{contest.contest_id}:period:{number}",
                contest_id=contest.contest_id,
                source_period_number=str(number),
                kind=kind,
                label=label,
                provider_namespace=authorities.NAMESPACE,
                start_ns=summary.first_time_ns,
                end_ns=summary.last_time_ns,
            )
        )
        trials.append(
            Trial(
                dataset_id=authorities.DATASET_ID,
                session_id=frame_clock.game_id,
                trial_id=f"period-{number}",
                label=label,
            )
        )
    original_context = base.sports_contexts[0]
    crosswalks = tuple(
        item.model_copy(
            update={
                "metadata": {
                    **item.metadata,
                    "play_by_play_available": True,
                    "tracking_available": True,
                    "period_count": len(periods),
                }
            }
        )
        if item.entity_kind is SportsEntityKind.CONTEST
        else item
        for item in original_context.crosswalks
    )
    sports_context = original_context.model_copy(
        update={"periods": tuple(periods), "crosswalks": crosswalks}
    )
    source_authorities = SourceAuthorities(
        frames=(authorities.coordinate_frame(),),
        clocks=(authorities.clock(),),
        synchronizations=(authorities.synchronization(),),
        spatial_references=(authorities.spatial_reference(),),
        surface_geometries=(authorities.surface_geometry(),),
        clock_mappings=authorities.clock_mappings(),
    )
    canonical_streams = tracking.streams()
    sensor_streams = tuple(
        SensorStream(
            dataset_id=stream.dataset_id,
            session_id=stream.session_id,
            stream_id=stream.stream_id,
            modality=Modality.TRACKING,
            measurement_class=MeasurementClass.MODEL_ESTIMATED,
            clock_id=stream.clock_id,
            synchronization_spec_id=stream.synchronization_spec_id,
            coordinate_frame_id=stream.coordinate_frame_id,
            trial_id=stream.trial_id,
            nominal_sampling_rate_hz=authorities.FRAME_RATE_HZ,
            si_units=("m",),
            source_unit="ft",
            stream_metadata=dict(stream.stream_metadata),
            data_grain=stream.grain,
        )
        for stream in canonical_streams
    )
    return replace(
        base,
        trials=tuple(trials),
        streams=sensor_streams,
        authorities=source_authorities,
        sports_contexts=(sports_context,),
        session_metadata={
            **base.session_metadata,
            "metadata_only": False,
            "source_frame_rate_hz": authorities.FRAME_RATE_HZ,
            "source_coordinate_unit": "ft",
            "source_spatial_reference_id": authorities.COURT_REFERENCE_ID,
            "canonical_coordinate_frame_id": authorities.COURT_FRAME_ID,
            "frame_count": frame_clock.frame_count,
            "dead_time_frames": frame_clock.dead_time_frames,
            "periods": [item.model_dump(mode="json") for item in periods],
        },
    )


__all__ = ["adapter_algorithm_spec", "materialized_domain"]
