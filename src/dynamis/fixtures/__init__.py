"""Deterministic synthetic fixtures for every V1 modality (not external data)."""

from dynamis.fixtures.synthetic import (
    ModalityFixture,
    all_fixtures,
    events_sequence,
    fixtures_by_modality,
    force_bodyweight_static,
    force_dynamic_vertical,
    gnss_constant_velocity,
    imu_deterministic_trace,
    lpt_constant_acceleration,
    pose_skeleton_trajectory,
    tracking_multi_object,
)

__all__ = [
    "ModalityFixture",
    "all_fixtures",
    "events_sequence",
    "fixtures_by_modality",
    "force_bodyweight_static",
    "force_dynamic_vertical",
    "gnss_constant_velocity",
    "imu_deterministic_trace",
    "lpt_constant_acceleration",
    "pose_skeleton_trajectory",
    "tracking_multi_object",
]
