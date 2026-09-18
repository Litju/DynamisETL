"""Declared authorities for the GymAware landmine press + vision release.

The verified archive contains no sample-level trajectory: ``LP_data.zip`` holds
per-set GymAware CSV exports (rep-level summary indicators) and a vision workbook
with one populated example row, plus YOLO training code and raw video. RES-98
therefore imports source-provided trial metrics only and fabricates no dense LPT
stream.

The two methods measure different effective radii; the study protocol records
the vision system using the full bar (about 2.20 m) and the GymAware attachment
an effective radius of about 2.05 m. That distinction is preserved as method
metadata and no cross-method correction of any kind is applied in RES-98.
"""

from __future__ import annotations

GYMAWARE_DATASET_ID = "gymaware-landmine-vision"
GYMAWARE_VERSION = "v1"

#: Structured members actually used by the adapter.
VISION_WORKBOOK_KEY = "LP_data/GA_vision_data.xlsx"
GYMAWARE_CSV_PREFIX = "LP_data/GymAware_rawdata/"

#: Method metadata preserved verbatim from the study protocol.
VISION_EFFECTIVE_RADIUS_M = 2.20
GYMAWARE_EFFECTIVE_RADIUS_M = 2.05
RADIUS_AUTHORITY = (
    "study protocol: vision uses the full bar length (~2.20 m); the GymAware "
    "attachment/effective radius is ~2.05 m. Recorded by the RES-98 execution lock; "
    "not independently re-measured in this repository."
)

#: Method identities used in metric provenance.
METHOD_GYMAWARE = "gymaware-rs"
METHOD_VISION = "vision-tracking"

#: Vision workbook metric sheets and the canonical metric each maps onto.
VISION_SHEET_METRICS: dict[str, str] = {
    "平均速度": "vision_mean_velocity",
    "峰值速度": "vision_peak_velocity",
    "峰值功率": "vision_peak_power",
    "平均功率": "vision_mean_power",
    "峰值力": "vision_peak_force",
    "平均力": "vision_mean_force",
}

#: GymAware CSV metric columns and the canonical metric each maps onto.
GYMAWARE_COLUMN_METRICS: dict[str, str] = {
    "mean_velocity": "gymaware_mean_velocity",
    "peak_velocity": "gymaware_peak_velocity",
    "peak_power": "gymaware_peak_power",
    "mean_power": "gymaware_mean_power",
    "peak_force": "gymaware_peak_force",
    "mean_force": "gymaware_mean_force",
}

#: Canonical metric identities: (metric_id, name, si_unit).
METRIC_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("gymaware_mean_velocity", "GymAware concentric mean velocity", "m/s"),
    ("gymaware_peak_velocity", "GymAware concentric peak velocity", "m/s"),
    ("gymaware_peak_power", "GymAware concentric peak power", "W"),
    ("gymaware_mean_power", "GymAware concentric mean power", "W"),
    ("gymaware_peak_force", "GymAware concentric peak force", "N"),
    ("gymaware_mean_force", "GymAware concentric mean force", "N"),
    ("vision_mean_velocity", "Vision-system mean velocity", "m/s"),
    ("vision_peak_velocity", "Vision-system peak velocity", "m/s"),
    ("vision_peak_power", "Vision-system peak power", "W"),
    ("vision_mean_power", "Vision-system mean power", "W"),
    ("vision_peak_force", "Vision-system peak force", "N"),
    ("vision_mean_force", "Vision-system mean force", "N"),
)

#: Vision workbook sheet -> canonical metric id.
WORKBOOK_SHEET_TO_METRIC = dict(VISION_SHEET_METRICS)


def method_radius_m(method: str) -> float:
    if method == METHOD_GYMAWARE:
        return GYMAWARE_EFFECTIVE_RADIUS_M
    if method == METHOD_VISION:
        return VISION_EFFECTIVE_RADIUS_M
    raise ValueError(f"unknown method {method!r}")
