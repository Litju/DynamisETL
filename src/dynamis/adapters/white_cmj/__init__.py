"""White CMJ accelerometer + vGRF anti-corruption adapter.

Provider: Zenodo record 10.5281/zenodo.19136480 (v1; declared CC-BY-4.0,
attribution required, redistribution conditional, per the RES-104 rights
audit). Canonical targets: per-trial ``imu_sample`` streams (full
accelerometer recording at 250 Hz converted from ``g`` to ``m/s²``) and
per-trial ``force_sample`` streams (pre-takeoff vGRF at 1000 Hz written to the
dimensionless ``force_z_body_weight_ratio`` field), plus source-provided
trial metrics.

The NPZ container is untrusted external input: members are enumerated and their
``.npy`` headers inspected before any value is read, and the pickle-serialized
object members are decoded only through the restricted numeric unpickler in
:mod:`dynamis.adapters.white_cmj.npz_safety`.
"""

from dynamis.adapters.white_cmj.adapter import (
    WHITE_DATASET_ID,
    WhiteCmjAdapter,
    WhiteTrial,
    canonical_trials,
)

__all__ = [
    "WHITE_DATASET_ID",
    "WhiteCmjAdapter",
    "WhiteTrial",
    "canonical_trials",
]
