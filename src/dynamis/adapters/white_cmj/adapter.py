"""White CMJ anti-corruption adapter: verified release -> canonical IMU/force streams.

Mapping (derived from the verified release, not from the record prose):

* one canonical ``imu_sample`` stream per trial from the distributed
  accelerometer member: full recording at the source-declared 250 Hz, three
  channels converted from ``g`` to ``m/s**2`` by the exact standard-gravity
  factor. The sensor frame keeps every axis explicitly unspecified because the
  release documents no orientation;
* one canonical ``force_sample`` stream per trial from the distributed vGRF
  member: pre-takeoff curve at the source-declared 1000 Hz, already normalised
  by body weight. Values are written to ``force_z_body_weight_ratio`` (unit
  ``1``); no newton value is fabricated because the release provides no body
  mass;
* ``t_rel_ns`` is takeoff-relative for both streams: the accelerometer is
  anchored at its provider takeoff index, the vGRF at its final (takeoff)
  sample. Both are ``SOURCE_DERIVED`` representations of a source-preprocessed
  release;
* a trial whose arrays are empty, non-finite or structurally inconsistent is
  quarantined whole with an explicit rule; nothing is silently dropped.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyarrow as pa

from dynamis.adapters.white_cmj import authorities
from dynamis.adapters.white_cmj.discovery import (
    WhiteCmjBundle,
    WhiteCmjDiscovery,
    discover_white_cmj,
)
from dynamis.contracts import (
    FORCE_SCHEMA,
    IMU_SCHEMA,
    AlgorithmKind,
    AlgorithmSpec,
    Device,
    MeasurementClass,
    Modality,
    ParticipantRole,
    SensorStream,
    Session,
    SessionKind,
    SessionParticipant,
    Subject,
    SyncAlignment,
    Trial,
)
from dynamis.pipeline.quarantine import (
    RULE_MISSING_PAIRING,
    RULE_NON_FINITE_VALUE,
    RULE_SHAPE_MISMATCH,
    RULE_TIME_OUT_OF_RANGE,
    QuarantinedRecord,
)
from dynamis.pipeline.source_metrics import SourceMetricObservation
from dynamis.pipeline.streams import (
    DEFAULT_BATCH_SIZE,
    CanonicalStream,
    ProviderDomain,
    SourceAuthorities,
)

WHITE_DATASET_ID = authorities.WHITE_DATASET_ID

#: Canonical force representation actually written by this adapter.
FORCE_RATIO_FIELD = "force_z_body_weight_ratio"

NULLABLE_IMU_PAYLOAD: dict[str, Any] = {
    "gyro_x_rad_s": None,
    "gyro_y_rad_s": None,
    "gyro_z_rad_s": None,
    "mag_x_ut": None,
    "mag_y_ut": None,
    "mag_z_ut": None,
    "temperature_deg_c": None,
    "quality_flag": None,
}

NULLABLE_FORCE_PAYLOAD: dict[str, Any] = {
    "plate_id": None,
    "force_x_n": None,
    "force_y_n": None,
    "force_z_n": None,
    "moment_x_n_m": None,
    "moment_y_n_m": None,
    "moment_z_n_m": None,
    "cop_x_m": None,
    "cop_y_m": None,
    "cop_z_m": None,
    "trigger_flag": None,
    "quality_flag": None,
}


def adapter_algorithm_spec() -> AlgorithmSpec:
    """Deterministic algorithm identity for the White CMJ adapter."""
    return AlgorithmSpec(
        algorithm_id="white_cmj_adapter",
        name="White CMJ accelerometer + vGRF anti-corruption adapter",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Streams the verified cmj_dataset_both.npz release into per-trial canonical "
            "imu_sample (g -> m/s**2) and force_sample (body-weight ratio) streams on a "
            "takeoff-relative 250 Hz / 1000 Hz axis. No biomechanical processor runs here."
        ),
    )


@dataclass(frozen=True, slots=True)
class WhiteTrial:
    """Deterministic canonical identity of one distributed CMJ trial."""

    row_index: int
    subject_id: str
    session_id: str
    trial_id: str
    condition: str
    condition_label: int
    original_participant_id: int
    ordinal_within_subject_condition: int


@dataclass(slots=True)
class TrialCounters:
    source_samples: int = 0
    canonical_rows: int = 0
    quarantined: list[QuarantinedRecord] = field(default_factory=list)

    @property
    def quarantined_rows(self) -> int:
        return sum(1 for _ in self.quarantined)


def subject_id_for(subject_index: int) -> str:
    return f"white-s{subject_index:03d}"


def session_id_for(subject_index: int) -> str:
    return f"white-s{subject_index:03d}"


def imu_stream_id(trial_id: str) -> str:
    return f"{authorities.ACC_STREAM_PREFIX}-{trial_id}"


def force_stream_id(trial_id: str) -> str:
    return f"{authorities.FORCE_STREAM_PREFIX}-{trial_id}"


class WhiteCmjAdapter:
    """Per-trial anti-corruption layer over one decoded release bundle."""

    def __init__(self, bundle: WhiteCmjBundle) -> None:
        self._bundle = bundle
        self._discovery = discover_white_cmj(bundle)
        self._trials = self._build_trials()
        self._counters: dict[str, TrialCounters] = {
            trial.trial_id: TrialCounters() for trial in self._trials
        }
        self._validated: dict[str, bool] = {}

    @property
    def bundle(self) -> WhiteCmjBundle:
        return self._bundle

    @property
    def discovery(self) -> WhiteCmjDiscovery:
        return self._discovery

    @property
    def trials(self) -> tuple[WhiteTrial, ...]:
        return self._trials

    def counters(self, trial_id: str) -> TrialCounters:
        return self._counters[trial_id]

    def trial_is_valid(self, trial: WhiteTrial) -> bool:
        return self._validate_trial(trial)

    def source_metrics(self) -> tuple[SourceMetricObservation, ...]:
        """Source-provided trial scalars, imported without recomputation."""
        metric_specs = (
            (
                "source_jump_height",
                "Source-provided countermovement jump height",
                "m",
                "jump_height",
            ),
            (
                "source_peak_power_relative",
                "Source-provided peak power (per body mass)",
                "W/kg",
                "peak_power",
            ),
        )
        observations: list[SourceMetricObservation] = []
        for trial in self._trials:
            if not self._validate_trial(trial):
                continue
            index = trial.row_index
            for metric_id, name, unit, member in metric_specs:
                value = float(
                    self._bundle.jump_height[index]
                    if member == "jump_height"
                    else self._bundle.peak_power[index]
                )
                if not np.isfinite(value):
                    self._counters[trial.trial_id].quarantined.append(
                        QuarantinedRecord(
                            rule=RULE_NON_FINITE_VALUE,
                            detail=f"source metric {member!r} is not finite",
                            dataset_id=WHITE_DATASET_ID,
                            session_id=trial.session_id,
                            stream_id=imu_stream_id(trial.trial_id),
                            subject_id=trial.subject_id,
                            source_record_id=f"row-{index}",
                            evidence={"metric": metric_id, "value": repr(value)},
                        )
                    )
                    continue
                observations.append(
                    SourceMetricObservation(
                        dataset_id=WHITE_DATASET_ID,
                        metric_id=metric_id,
                        name=name,
                        si_unit=unit,
                        measurement_class=MeasurementClass.SOURCE_DERIVED,
                        value=value,
                        source_field=member,
                        source_key=authorities.WHITE_NPZ_KEY,
                        session_id=trial.session_id,
                        subject_id=trial.subject_id,
                        trial_id=trial.trial_id,
                        provenance={
                            "source_member": member,
                            "source_row_index": index,
                            "condition": trial.condition,
                            "source_condition_label": trial.condition_label,
                            "source_original_participant_id": trial.original_participant_id,
                            "sensor_placement_authority": (authorities.SENSOR_PLACEMENT_AUTHORITY),
                            "recomputed_by_dynamis": False,
                        },
                    )
                )
        return tuple(observations)

    def source_authorities(self) -> SourceAuthorities:
        alignments = tuple(
            SyncAlignment(
                source_stream_id=force_stream_id(trial.trial_id),
                target_stream_id=imu_stream_id(trial.trial_id),
                offset_ns=0,
                scale=1.0,
                sync_spec_id=authorities.SYNC_SPEC_ID,
                notes=(
                    "Released arrays share the source-provided takeoff axis for this trial; "
                    "scale 1 / offset 0 states that shared axis, not zero instrument error."
                ),
            )
            for trial in self._trials
        )
        return SourceAuthorities(
            frames=(authorities.sensor_frame(), authorities.plate_frame()),
            clocks=(authorities.takeoff_clock(),),
            synchronizations=(authorities.source_sync_spec(),),
            alignments=alignments,
        )

    def devices(self) -> tuple[Device, ...]:
        return (
            Device(
                dataset_id=WHITE_DATASET_ID,
                device_id=authorities.TRIGNO_DEVICE_ID,
                device_type="imu",
                vendor="Delsys",
                model="Trigno",
                specs={
                    "original_measurement": "triaxial acceleration",
                    "distributed_representation": "source-preprocessed arrays in g",
                    "distributed_rate_hz": self._bundle.acc_sampling_rate_hz,
                    "placement_distributed_record": authorities.SENSOR_PLACEMENT_DISTRIBUTED_RECORD,
                    "placement_original_paper": authorities.SENSOR_PLACEMENT_ORIGINAL_PAPER,
                    "placement_authority": authorities.SENSOR_PLACEMENT_AUTHORITY,
                },
            ),
            Device(
                dataset_id=WHITE_DATASET_ID,
                device_id=authorities.KISTLER_DEVICE_ID,
                device_type="force_platform",
                vendor="Kistler",
                model="portable force platforms (two)",
                specs={
                    "original_acquisition_rate_hz": 1000,
                    "distributed_rate_hz": self._bundle.grf_sampling_rate_hz,
                    "distributed_representation": (
                        "source-preprocessed pre-takeoff vertical force, body-weight normalised"
                    ),
                },
            ),
        )

    def domain(self) -> ProviderDomain:
        sessions: list[Session] = []
        subjects: list[Subject] = []
        participants: list[SessionParticipant] = []
        seen_subjects: set[int] = set()
        for trial in self._trials:
            index = int(self._bundle.subject_ids[trial.row_index])
            if index in seen_subjects:
                continue
            seen_subjects.add(index)
            sessions.append(
                Session(
                    dataset_id=WHITE_DATASET_ID,
                    session_id=trial.session_id,
                    kind=SessionKind.LABORATORY,
                    label=(
                        f"Released CMJ trials for dataset subject {index}; the provider "
                        "distributes no visit/session boundary"
                    ),
                )
            )
            subjects.append(
                Subject(
                    dataset_id=WHITE_DATASET_ID,
                    subject_id=trial.subject_id,
                    sex="unspecified",
                    cohort="quality-excluded release subset (663 of 691 trials)",
                    notes=(
                        f"source original_participant_id={trial.original_participant_id}; "
                        "distributed n_subjects member = "
                        f"{self._bundle.declared_n_subjects} but only "
                        f"{self._discovery.subject_id_count} subject ids are present in the "
                        "accepted arrays"
                    ),
                )
            )
            participants.append(
                SessionParticipant(
                    dataset_id=WHITE_DATASET_ID,
                    session_id=trial.session_id,
                    subject_id=trial.subject_id,
                    role=ParticipantRole.PARTICIPANT,
                )
            )
        trials = tuple(
            Trial(
                dataset_id=WHITE_DATASET_ID,
                session_id=trial.session_id,
                trial_id=trial.trial_id,
                subject_id=trial.subject_id,
                label=(
                    f"condition={trial.condition}; source_row={trial.row_index}; "
                    f"acc_takeoff_index={int(self._bundle.acc_takeoff[trial.row_index])}; "
                    f"grf_source_takeoff_index={int(self._bundle.grf_takeoff[trial.row_index])}"
                ),
            )
            for trial in self._trials
        )
        streams = tuple(
            stream
            for trial in self._trials
            if self._validate_trial(trial)
            for stream in (
                self.sensor_stream(trial, Modality.IMU),
                self.sensor_stream(trial, Modality.FORCE),
            )
        )
        return ProviderDomain(
            session=None,
            sessions=tuple(sessions),
            subjects=tuple(subjects),
            participants=tuple(participants),
            trials=trials,
            streams=streams,
            authorities=self.source_authorities(),
            devices=self.devices(),
            session_metadata={
                "source_key": authorities.WHITE_NPZ_KEY,
                "trial_count": self._bundle.trial_count,
                "subject_id_count": self._discovery.subject_id_count,
                "declared_n_subjects": self._bundle.declared_n_subjects,
                "condition_counts": self._discovery.condition_counts,
                "acc_rate_hz": self._bundle.acc_sampling_rate_hz,
                "grf_rate_hz": self._bundle.grf_sampling_rate_hz,
                "measurement_class": MeasurementClass.SOURCE_DERIVED.value,
                "session_model": "one session per dataset subject; no visit boundaries distributed",
                "sensor_placement": {
                    "distributed_record": authorities.SENSOR_PLACEMENT_DISTRIBUTED_RECORD,
                    "original_paper": authorities.SENSOR_PLACEMENT_ORIGINAL_PAPER,
                    "authority": authorities.SENSOR_PLACEMENT_AUTHORITY,
                },
            },
            participants_ignored={
                "declared n_subjects member value minus present subject ids": max(
                    self._bundle.declared_n_subjects - self._discovery.subject_id_count, 0
                )
            },
        )

    def canonical_stream(self, trial: WhiteTrial, modality: Modality) -> CanonicalStream:
        """Canonical stream for one trial/modality, quarantining invalid trials."""
        index = trial.row_index
        if modality is Modality.IMU:
            return CanonicalStream(
                dataset_id=WHITE_DATASET_ID,
                session_id=trial.session_id,
                stream_id=imu_stream_id(trial.trial_id),
                modality=Modality.IMU,
                measurement_class=MeasurementClass.SOURCE_DERIVED,
                clock_id=authorities.CLOCK_ID,
                synchronization_spec_id=authorities.SYNC_SPEC_ID,
                coordinate_frame_id=authorities.SENSOR_FRAME_ID,
                trial_id=trial.trial_id,
                subject_id=trial.subject_id,
                device_id=authorities.TRIGNO_DEVICE_ID,
                nominal_sampling_rate_hz=float(self._bundle.acc_sampling_rate_hz),
                source_unit="g",
                stream_metadata=self._stream_metadata(trial, index, "g"),
                schema=IMU_SCHEMA,
                batches=self._imu_batches(trial, index),
            )
        return CanonicalStream(
            dataset_id=WHITE_DATASET_ID,
            session_id=trial.session_id,
            stream_id=force_stream_id(trial.trial_id),
            modality=Modality.FORCE,
            measurement_class=MeasurementClass.SOURCE_DERIVED,
            clock_id=authorities.CLOCK_ID,
            synchronization_spec_id=authorities.SYNC_SPEC_ID,
            coordinate_frame_id=authorities.PLATE_FRAME_ID,
            trial_id=trial.trial_id,
            subject_id=trial.subject_id,
            device_id=authorities.KISTLER_DEVICE_ID,
            nominal_sampling_rate_hz=float(self._bundle.grf_sampling_rate_hz),
            source_unit="1",
            stream_metadata=self._stream_metadata(trial, index, "1"),
            schema=FORCE_SCHEMA,
            batches=self._force_batches(trial, index),
        )

    def sensor_stream(self, trial: WhiteTrial, modality: Modality) -> SensorStream:
        """Declared control-plane stream for one trial/modality."""
        if modality is Modality.IMU:
            return SensorStream(
                dataset_id=WHITE_DATASET_ID,
                session_id=trial.session_id,
                stream_id=imu_stream_id(trial.trial_id),
                modality=Modality.IMU,
                measurement_class=MeasurementClass.SOURCE_DERIVED,
                clock_id=authorities.CLOCK_ID,
                synchronization_spec_id=authorities.SYNC_SPEC_ID,
                coordinate_frame_id=authorities.SENSOR_FRAME_ID,
                trial_id=trial.trial_id,
                subject_id=trial.subject_id,
                device_id=authorities.TRIGNO_DEVICE_ID,
                nominal_sampling_rate_hz=float(self._bundle.acc_sampling_rate_hz),
                si_units=("m/s**2",),
                source_unit="g",
                stream_metadata=self._stream_metadata(trial, trial.row_index, "g"),
            )
        return SensorStream(
            dataset_id=WHITE_DATASET_ID,
            session_id=trial.session_id,
            stream_id=force_stream_id(trial.trial_id),
            modality=Modality.FORCE,
            measurement_class=MeasurementClass.SOURCE_DERIVED,
            clock_id=authorities.CLOCK_ID,
            synchronization_spec_id=authorities.SYNC_SPEC_ID,
            coordinate_frame_id=authorities.PLATE_FRAME_ID,
            trial_id=trial.trial_id,
            subject_id=trial.subject_id,
            device_id=authorities.KISTLER_DEVICE_ID,
            nominal_sampling_rate_hz=float(self._bundle.grf_sampling_rate_hz),
            si_units=("1",),
            source_unit="1",
            stream_metadata=self._stream_metadata(trial, trial.row_index, "1"),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _stream_metadata(self, trial: WhiteTrial, index: int, source_unit: str) -> dict[str, Any]:
        return {
            "adapter": "white_cmj",
            "source_key": authorities.WHITE_NPZ_KEY,
            "source_row_index": index,
            "condition": trial.condition,
            "source_condition_label": trial.condition_label,
            "source_original_participant_id": trial.original_participant_id,
            "acc_takeoff_index": int(self._bundle.acc_takeoff[index]),
            "grf_source_takeoff_index": int(self._bundle.grf_takeoff[index]),
            "source_unit": source_unit,
            "measurement_class": MeasurementClass.SOURCE_DERIVED.value,
            "sensor_placement_distributed_record": (
                authorities.SENSOR_PLACEMENT_DISTRIBUTED_RECORD
            ),
            "sensor_placement_original_paper": authorities.SENSOR_PLACEMENT_ORIGINAL_PAPER,
            "sensor_placement_authority": authorities.SENSOR_PLACEMENT_AUTHORITY,
        }

    def _build_trials(self) -> tuple[WhiteTrial, ...]:
        counts: dict[tuple[int, int], int] = {}
        trials: list[WhiteTrial] = []
        for row_index in range(self._bundle.trial_count):
            subject_index = int(self._bundle.subject_ids[row_index])
            label = int(self._bundle.condition_labels[row_index])
            condition = authorities.CONDITION_LABELS.get(label)
            if condition is None:
                condition = f"condition-{label}"
            ordinal = counts.get((subject_index, label), 0)
            counts[(subject_index, label)] = ordinal + 1
            trials.append(
                WhiteTrial(
                    row_index=row_index,
                    subject_id=subject_id_for(subject_index),
                    session_id=session_id_for(subject_index),
                    trial_id=f"white-s{subject_index:03d}-{condition}-t{ordinal:02d}",
                    condition=condition,
                    condition_label=label,
                    original_participant_id=int(self._bundle.original_participant_ids[row_index]),
                    ordinal_within_subject_condition=ordinal,
                )
            )
        return tuple(trials)

    def _trial_arrays(self, trial: WhiteTrial) -> tuple[np.ndarray, np.ndarray]:
        return (
            self._bundle.acc_signals[trial.row_index],
            self._bundle.grf_signals[trial.row_index],
        )

    def _validate_trial(self, trial: WhiteTrial) -> bool:
        """Structural/finite validation once per trial; quarantines on failure."""
        if trial.trial_id in self._validated:
            return self._validated[trial.trial_id]
        counters = self._counters[trial.trial_id]
        acc, grf = self._trial_arrays(trial)
        acc_stream = imu_stream_id(trial.trial_id)
        force_stream = force_stream_id(trial.trial_id)
        counters.source_samples = int(acc.shape[0]) + int(grf.shape[0])

        def quarantine(rule: str, detail: str, stream_id: str, evidence: dict[str, Any]) -> None:
            counters.quarantined.append(
                QuarantinedRecord(
                    rule=rule,
                    detail=detail,
                    dataset_id=WHITE_DATASET_ID,
                    session_id=trial.session_id,
                    stream_id=stream_id,
                    subject_id=trial.subject_id,
                    source_record_id=f"row-{trial.row_index}",
                    evidence=evidence,
                )
            )

        valid = True
        if acc.ndim != 2 or acc.shape[1] != 3:
            quarantine(
                RULE_SHAPE_MISMATCH,
                "accelerometer trial array must be (samples, 3)",
                acc_stream,
                {"shape": list(acc.shape)},
            )
            valid = False
        elif acc.shape[0] == 0:
            quarantine(
                RULE_MISSING_PAIRING,
                "accelerometer trial array carries no samples",
                acc_stream,
                {"shape": list(acc.shape)},
            )
            valid = False
        if grf.ndim != 1 or grf.shape[0] == 0:
            quarantine(
                RULE_MISSING_PAIRING,
                "vGRF trial array is empty or not one-dimensional",
                force_stream,
                {"shape": list(grf.shape)},
            )
            valid = False
        if valid:
            takeoff = int(self._bundle.acc_takeoff[trial.row_index])
            if not 0 <= takeoff < acc.shape[0]:
                quarantine(
                    RULE_TIME_OUT_OF_RANGE,
                    "accelerometer takeoff index is outside the distributed trial",
                    acc_stream,
                    {"takeoff_index": takeoff, "samples": int(acc.shape[0])},
                )
                valid = False
        if valid:
            for stream_id, array in ((acc_stream, acc), (force_stream, grf)):
                if array.size and not bool(np.isfinite(array).all()):
                    quarantine(
                        RULE_NON_FINITE_VALUE,
                        "trial array contains NaN or infinite values",
                        stream_id,
                        {"non_finite_values": int(array.size - np.isfinite(array).sum())},
                    )
                    valid = False
        self._validated[trial.trial_id] = valid
        return valid

    def _relative_ns(self, sample_index: int, takeoff_index: int, rate_hz: int) -> int:
        if 1_000_000_000 % rate_hz != 0:
            raise ValueError(
                f"source rate {rate_hz} Hz is not representable in integer nanoseconds"
            )
        return (sample_index - takeoff_index) * (1_000_000_000 // rate_hz)

    def _imu_batches(self, trial: WhiteTrial, index: int) -> Iterator[pa.RecordBatch]:
        if not self._validate_trial(trial):
            return
        counters = self._counters[trial.trial_id]
        array = self._bundle.acc_signals[index]
        takeoff = int(self._bundle.acc_takeoff[index])
        rate = self._bundle.acc_sampling_rate_hz
        rows: list[dict[str, Any]] = []
        for sample_index in range(int(array.shape[0])):
            rows.append(
                {
                    "dataset_id": WHITE_DATASET_ID,
                    "session_id": trial.session_id,
                    "trial_id": trial.trial_id,
                    "subject_id": trial.subject_id,
                    "device_id": authorities.TRIGNO_DEVICE_ID,
                    "stream_id": imu_stream_id(trial.trial_id),
                    "sample_index": sample_index,
                    "t_rel_ns": self._relative_ns(sample_index, takeoff, rate),
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": float(rate),
                    "measurement_class": MeasurementClass.SOURCE_DERIVED.value,
                    "clock_id": authorities.CLOCK_ID,
                    "synchronization_spec_id": authorities.SYNC_SPEC_ID,
                    "coordinate_frame_id": authorities.SENSOR_FRAME_ID,
                    "accel_x_m_s2": float(array[sample_index, 0])
                    * authorities.STANDARD_GRAVITY_M_S2,
                    "accel_y_m_s2": float(array[sample_index, 1])
                    * authorities.STANDARD_GRAVITY_M_S2,
                    "accel_z_m_s2": float(array[sample_index, 2])
                    * authorities.STANDARD_GRAVITY_M_S2,
                    **NULLABLE_IMU_PAYLOAD,
                }
            )
            if len(rows) >= DEFAULT_BATCH_SIZE:
                counters.canonical_rows += len(rows)
                yield pa.RecordBatch.from_pylist(rows, schema=IMU_SCHEMA)
                rows = []
        if rows:
            counters.canonical_rows += len(rows)
            yield pa.RecordBatch.from_pylist(rows, schema=IMU_SCHEMA)

    def _force_batches(self, trial: WhiteTrial, index: int) -> Iterator[pa.RecordBatch]:
        if not self._validate_trial(trial):
            return
        counters = self._counters[trial.trial_id]
        array = self._bundle.grf_signals[index]
        rate = self._bundle.grf_sampling_rate_hz
        samples = int(array.shape[0])
        # The released pre-takeoff curve ends at the takeoff instant, so its final
        # sample is t_rel_ns = 0. The provider's grf_takeoff member is an
        # original-source index and is deliberately not used to index this array.
        takeoff = samples - 1
        rows: list[dict[str, Any]] = []
        for sample_index in range(samples):
            rows.append(
                {
                    "dataset_id": WHITE_DATASET_ID,
                    "session_id": trial.session_id,
                    "trial_id": trial.trial_id,
                    "subject_id": trial.subject_id,
                    "device_id": authorities.KISTLER_DEVICE_ID,
                    "stream_id": force_stream_id(trial.trial_id),
                    "sample_index": sample_index,
                    "t_rel_ns": self._relative_ns(sample_index, takeoff, rate),
                    "timestamp_utc_ns": None,
                    "nominal_sampling_rate_hz": float(rate),
                    "measurement_class": MeasurementClass.SOURCE_DERIVED.value,
                    "clock_id": authorities.CLOCK_ID,
                    "synchronization_spec_id": authorities.SYNC_SPEC_ID,
                    "coordinate_frame_id": authorities.PLATE_FRAME_ID,
                    FORCE_RATIO_FIELD: float(array[sample_index]),
                    **NULLABLE_FORCE_PAYLOAD,
                }
            )
            if len(rows) >= DEFAULT_BATCH_SIZE:
                counters.canonical_rows += len(rows)
                yield pa.RecordBatch.from_pylist(rows, schema=FORCE_SCHEMA)
                rows = []
        if rows:
            counters.canonical_rows += len(rows)
            yield pa.RecordBatch.from_pylist(rows, schema=FORCE_SCHEMA)


def canonical_trials(bundle: WhiteCmjBundle) -> tuple[WhiteCmjAdapter, tuple[WhiteTrial, ...]]:
    adapter = WhiteCmjAdapter(bundle)
    return adapter, adapter.trials
