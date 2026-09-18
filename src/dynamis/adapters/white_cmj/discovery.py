"""Structural discovery of the verified White CMJ ``.npz`` release.

Member names, shapes and semantics below were derived from the verified
``cmj_dataset_both.npz`` bytes and the provider's own preparation code
(``scripts/prepare_dataset.py`` in ``markgewhite/acc2grf-cmj``), never from
memory. The loader refuses to proceed if the verified member set changes, and
records every unmapped extra member instead of ignoring it.

The receipt intentionally contains no signal values: only names, shapes, dtypes,
container sizes and counts.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dynamis.adapters.white_cmj import authorities
from dynamis.adapters.white_cmj.npz_safety import (
    NpzMemberHeader,
    inspect_npz_archive,
    load_numeric_member,
    load_object_member_numeric,
)

#: Verified member names of ``cmj_dataset_both.npz`` (provider schema, not a guess).
ACC_SIGNALS = "acc_signals"
GRF_SIGNALS = "grf_signals"
ACC_TAKEOFF = "acc_takeoff"
GRF_TAKEOFF = "grf_takeoff"
SUBJECT_IDS = "subject_ids"
ORIGINAL_PARTICIPANT_IDS = "original_participant_ids"
JUMP_HEIGHT = "jump_height"
PEAK_POWER = "peak_power"
CONDITION_LABELS = "condition_labels"
ACC_SAMPLING_RATE = "acc_sampling_rate"
GRF_SAMPLING_RATE = "grf_sampling_rate"
N_SUBJECTS = "n_subjects"

REQUIRED_MEMBERS: tuple[str, ...] = (
    ACC_SIGNALS,
    GRF_SIGNALS,
    ACC_TAKEOFF,
    GRF_TAKEOFF,
    SUBJECT_IDS,
    ORIGINAL_PARTICIPANT_IDS,
    JUMP_HEIGHT,
    PEAK_POWER,
    CONDITION_LABELS,
    ACC_SAMPLING_RATE,
    GRF_SAMPLING_RATE,
    N_SUBJECTS,
)

PER_TRIAL_VECTOR_MEMBERS: tuple[str, ...] = (
    ACC_TAKEOFF,
    GRF_TAKEOFF,
    SUBJECT_IDS,
    ORIGINAL_PARTICIPANT_IDS,
    JUMP_HEIGHT,
    PEAK_POWER,
    CONDITION_LABELS,
)

SCALAR_MEMBERS: tuple[str, ...] = (ACC_SAMPLING_RATE, GRF_SAMPLING_RATE, N_SUBJECTS)


class WhiteSourceError(ValueError):
    """The released container no longer matches the verified provider schema."""


@dataclass(frozen=True, slots=True)
class WhiteCmjBundle:
    """One verified release decoded into per-trial arrays (no values mutated)."""

    members: tuple[NpzMemberHeader, ...]
    acc_signals: tuple[np.ndarray, ...]
    grf_signals: tuple[np.ndarray, ...]
    acc_takeoff: np.ndarray
    grf_takeoff: np.ndarray
    subject_ids: np.ndarray
    original_participant_ids: np.ndarray
    jump_height: np.ndarray
    peak_power: np.ndarray
    condition_labels: np.ndarray
    acc_sampling_rate_hz: int
    grf_sampling_rate_hz: int
    declared_n_subjects: int
    unmapped_members: tuple[str, ...]

    @property
    def trial_count(self) -> int:
        return len(self.acc_signals)

    def acc_sample_counts(self) -> tuple[int, ...]:
        return tuple(int(array.shape[0]) for array in self.acc_signals)

    def grf_sample_counts(self) -> tuple[int, ...]:
        return tuple(int(array.shape[0]) for array in self.grf_signals)


def _scalar_int(array: np.ndarray, member: str) -> int:
    if array.size != 1:
        raise WhiteSourceError(f"{member}: expected a scalar, found shape {array.shape}")
    value = array.reshape(-1)[0]
    if not np.issubdtype(array.dtype, np.integer):
        raise WhiteSourceError(f"{member}: expected an integer scalar, found {array.dtype}")
    return int(value)


def load_white_cmj_bundle(path: Path | str) -> WhiteCmjBundle:
    """Decode the verified release through the restricted NPZ safety path."""
    with zipfile.ZipFile(Path(path)) as archive:
        members = inspect_npz_archive(archive)
        by_name = {member.name[: -len(".npy")]: member for member in members}
        missing = [name for name in REQUIRED_MEMBERS if name not in by_name]
        if missing:
            raise WhiteSourceError(
                f"verified White CMJ member set changed; missing members: {missing}"
            )
        unmapped = tuple(sorted(set(by_name) - set(REQUIRED_MEMBERS)))
        acc_signals = load_object_member_numeric(archive, f"{ACC_SIGNALS}.npy", expected_ndim=2)
        grf_signals = load_object_member_numeric(archive, f"{GRF_SIGNALS}.npy", expected_ndim=1)
        vectors = {
            name: load_numeric_member(archive, f"{name}.npy") for name in PER_TRIAL_VECTOR_MEMBERS
        }
        scalars = {name: load_numeric_member(archive, f"{name}.npy") for name in SCALAR_MEMBERS}

    trial_count = len(acc_signals)
    if len(grf_signals) != trial_count:
        raise WhiteSourceError(
            f"accelerometer and force members disagree on trial count: "
            f"{trial_count} != {len(grf_signals)}"
        )
    if trial_count == 0:
        raise WhiteSourceError("the release contains no trials")
    for name in PER_TRIAL_VECTOR_MEMBERS:
        if vectors[name].shape != (trial_count,):
            raise WhiteSourceError(
                f"{name}: expected shape ({trial_count},), found {vectors[name].shape}"
            )
    acc_rate = _scalar_int(scalars[ACC_SAMPLING_RATE], ACC_SAMPLING_RATE)
    grf_rate = _scalar_int(scalars[GRF_SAMPLING_RATE], GRF_SAMPLING_RATE)
    declared_subjects = _scalar_int(scalars[N_SUBJECTS], N_SUBJECTS)
    if acc_rate <= 0 or grf_rate <= 0:
        raise WhiteSourceError(f"declared sampling rates must be positive: {acc_rate}/{grf_rate}")
    return WhiteCmjBundle(
        members=members,
        acc_signals=tuple(acc_signals),
        grf_signals=tuple(grf_signals),
        acc_takeoff=vectors[ACC_TAKEOFF],
        grf_takeoff=vectors[GRF_TAKEOFF],
        subject_ids=vectors[SUBJECT_IDS],
        original_participant_ids=vectors[ORIGINAL_PARTICIPANT_IDS],
        jump_height=vectors[JUMP_HEIGHT],
        peak_power=vectors[PEAK_POWER],
        condition_labels=vectors[CONDITION_LABELS],
        acc_sampling_rate_hz=acc_rate,
        grf_sampling_rate_hz=grf_rate,
        declared_n_subjects=declared_subjects,
        unmapped_members=unmapped,
    )


def _vector_facts(values: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(values)
    facts: dict[str, Any] = {
        "dtype": values.dtype.str,
        "finite_count": int(finite.sum()),
        "non_finite_count": int(values.size - finite.sum()),
        "distinct_count": int(np.unique(values[finite]).size) if finite.any() else 0,
    }
    if finite.any() and np.issubdtype(values.dtype, np.number):
        valid = values[finite]
        facts["min"] = float(np.min(valid))
        facts["max"] = float(np.max(valid))
    return facts


@dataclass(frozen=True, slots=True)
class WhiteCmjDiscovery:
    """Structural receipt of the verified White CMJ release."""

    members: tuple[NpzMemberHeader, ...]
    trial_count: int
    subject_id_count: int
    original_participant_id_count: int
    declared_n_subjects: int
    condition_counts: dict[str, int]
    condition_representation: dict[str, Any]
    acc_sampling_rate_hz: int
    grf_sampling_rate_hz: int
    acc_sample_counts: dict[str, Any]
    grf_sample_counts: dict[str, Any]
    acc_channels: tuple[int, ...]
    acc_dtypes: tuple[str, ...]
    grf_dtypes: tuple[str, ...]
    acc_non_finite: int
    grf_non_finite: int
    acc_takeoff: dict[str, Any]
    grf_takeoff: dict[str, Any]
    jump_height: dict[str, Any]
    peak_power: dict[str, Any]
    unmapped_members: tuple[str, ...]
    pickle_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "container": {
                "member_count": len(self.members),
                "members": [member.to_dict() for member in self.members],
                "unmapped_members": list(self.unmapped_members),
            },
            "structure": {
                "trial_dimension": self.trial_count,
                "subject_count_present": self.subject_id_count,
                "original_participant_id_count": self.original_participant_id_count,
                "n_subjects_member_value": self.declared_n_subjects,
                "condition_representation": self.condition_representation,
                "condition_counts": self.condition_counts,
                "acc_sampling_rate_hz": self.acc_sampling_rate_hz,
                "grf_sampling_rate_hz": self.grf_sampling_rate_hz,
                "acc_channels": list(self.acc_channels),
                "acc_dtypes": list(self.acc_dtypes),
                "grf_dtypes": list(self.grf_dtypes),
                "acc_sample_count_per_trial": self.acc_sample_counts,
                "grf_sample_count_per_trial": self.grf_sample_counts,
                "acc_non_finite_values": self.acc_non_finite,
                "grf_non_finite_values": self.grf_non_finite,
            },
            "timing": {
                "acc_takeoff": self.acc_takeoff,
                "grf_takeoff": self.grf_takeoff,
                "takeoff_annotation": (
                    "acc_takeoff indexes the distributed 250 Hz accelerometer recording; "
                    "grf_takeoff is the provider's original-source takeoff index and is not "
                    "an index into the distributed pre-takeoff vGRF member"
                ),
            },
            "source_metrics": {
                "jump_height": self.jump_height,
                "peak_power": self.peak_power,
            },
            "safety": {
                "pickle_path": self.pickle_path,
                "allow_pickle": False,
                "object_member_policy": (
                    "object members decoded only through the restricted numeric unpickler; "
                    "every element must be a plain numeric numpy.ndarray"
                ),
            },
        }


def _counts_facts(counts: tuple[int, ...]) -> dict[str, Any]:
    return {
        "count": len(counts),
        "min": min(counts),
        "max": max(counts),
        "sum": sum(counts),
        "per_trial": list(counts),
    }


def discover_white_cmj(bundle: WhiteCmjBundle) -> WhiteCmjDiscovery:
    """Derive the structural discovery receipt from one decoded release bundle."""
    acc_counts = bundle.acc_sample_counts()
    grf_counts = bundle.grf_sample_counts()
    acc_shapes = {int(array.shape[1]) for array in bundle.acc_signals}
    acc_dtypes = tuple(sorted({array.dtype.str for array in bundle.acc_signals}))
    grf_dtypes = tuple(sorted({array.dtype.str for array in bundle.grf_signals}))
    acc_non_finite = sum(int(array.size - np.isfinite(array).sum()) for array in bundle.acc_signals)
    grf_non_finite = sum(int(array.size - np.isfinite(array).sum()) for array in bundle.grf_signals)
    conditions: dict[str, int] = {}
    for label in np.unique(bundle.condition_labels):
        conditions[str(int(label))] = int((bundle.condition_labels == label).sum())
    grf_within = int(
        np.sum(
            [
                int(index) < count
                for index, count in zip(bundle.grf_takeoff, grf_counts, strict=True)
            ]
        )
    )
    takeoff_delta_ms = (
        bundle.grf_takeoff.astype(np.float64) / bundle.grf_sampling_rate_hz * 1000.0
        - bundle.acc_takeoff.astype(np.float64) / bundle.acc_sampling_rate_hz * 1000.0
    )
    acc_takeoff_facts = _vector_facts(bundle.acc_takeoff.astype(np.float64))
    acc_takeoff_facts["within_trial_bounds"] = int(
        np.sum(
            [
                int(index) < count
                for index, count in zip(bundle.acc_takeoff, acc_counts, strict=True)
            ]
        )
    )
    grf_takeoff_facts = _vector_facts(bundle.grf_takeoff.astype(np.float64))
    grf_takeoff_facts["within_distributed_trial_bounds"] = grf_within
    grf_takeoff_facts["takeoff_time_delta_ms_min"] = float(np.min(takeoff_delta_ms))
    grf_takeoff_facts["takeoff_time_delta_ms_max"] = float(np.max(takeoff_delta_ms))
    return WhiteCmjDiscovery(
        members=bundle.members,
        trial_count=bundle.trial_count,
        subject_id_count=int(np.unique(bundle.subject_ids).size),
        original_participant_id_count=int(np.unique(bundle.original_participant_ids).size),
        declared_n_subjects=bundle.declared_n_subjects,
        condition_counts=conditions,
        condition_representation={
            "member": CONDITION_LABELS,
            "vocabulary": {str(key): value for key, value in authorities.CONDITION_LABELS.items()},
            "authority": "provider preparation code (CONDITION_INDICES)",
        },
        acc_sampling_rate_hz=bundle.acc_sampling_rate_hz,
        grf_sampling_rate_hz=bundle.grf_sampling_rate_hz,
        acc_sample_counts=_counts_facts(acc_counts),
        grf_sample_counts=_counts_facts(grf_counts),
        acc_channels=tuple(sorted(acc_shapes)),
        acc_dtypes=acc_dtypes,
        grf_dtypes=grf_dtypes,
        acc_non_finite=acc_non_finite,
        grf_non_finite=grf_non_finite,
        acc_takeoff=acc_takeoff_facts,
        grf_takeoff=grf_takeoff_facts,
        jump_height=_vector_facts(bundle.jump_height),
        peak_power=_vector_facts(bundle.peak_power),
        unmapped_members=bundle.unmapped_members,
        pickle_path=(
            "restricted numerical unpickler (numpy.ndarray/dtype/_reconstruct only; "
            "no allow_pickle=True)"
        ),
    )


def discover_white_cmj_file(path: Path | str) -> WhiteCmjDiscovery:
    return discover_white_cmj(load_white_cmj_bundle(path))
