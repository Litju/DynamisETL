"""Demo/materialization preparation contract (no services, no real data)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from benchmarks.tactical import _events, _tracking

from dynamis.demo.prepare import FLAGSHIPS, flagship_urls
from dynamis.processors.corpus import SilverStreamRef
from dynamis.processors.tactical_corpus import (
    LEVEL_SERIES,
    TRACKING_LEVELS,
    matchlab_v3_parameters,
    supported_levels,
)
from dynamis.processors.tactical_events import process_tactical_event_snapshots


def test_levels_follow_the_capability_authority() -> None:
    assert supported_levels("dfl-sportec-idsse") == ("A", "B", "C", "D", "V3")
    assert supported_levels("skillcorner-opendata") == ("A", "B", "C", "V3")
    assert supported_levels("womens-soccer-positioning") == ()
    assert supported_levels("unknown-dataset") == ()


def test_required_series_are_what_the_processors_emit() -> None:
    tracking = _tracking(frame_count=30)
    for level, processor in TRACKING_LEVELS.items():
        emitted = {series.name for series in processor(tracking).series}
        assert set(LEVEL_SERIES[level]) <= emitted, level
    events = process_tactical_event_snapshots(_events(), tracking)
    assert set(LEVEL_SERIES["D"]) <= {series.name for series in events.series}


def test_flagship_urls_cover_field_and_pose() -> None:
    urls = flagship_urls("http://127.0.0.1:5173/")
    assert urls[0] == "http://127.0.0.1:5173/catalog"
    for flagship in FLAGSHIPS:
        lab = f"http://127.0.0.1:5173/lab/{flagship.dataset_id}/{flagship.session_id}"
        assert f"{lab}?view=field&stream={flagship.field_stream}&tactical=live" in urls
        if flagship.pose_stream is not None:
            assert f"{lab}?view=pose&stream={flagship.pose_stream}" in urls
    assert any("view=pose" in url for url in urls)


def test_matchlab_v3_parameters_use_registered_pitch_metres() -> None:
    ref = SilverStreamRef(
        dataset_id="example",
        session_id="session",
        stream_id="tracking-period-1",
        modality="tracking",
        trial_id="period-1",
        subject_id=None,
        relative_path="tracking.parquet",
        checksum_sha256="sha256",
        row_count=1,
        nominal_sampling_rate_hz=25.0,
        coordinate_frame_id="pitch-center-m",
        stream_metadata={"pitch_dimensions_m": {"length_m": 120.0, "width_m": 80.0}},
    )

    assert matchlab_v3_parameters(ref) == {"pitch_length_m": 120.0, "pitch_width_m": 80.0}
    with pytest.raises(ValueError, match="requires registered pitch_dimensions_m"):
        matchlab_v3_parameters(replace(ref, stream_metadata={}))
