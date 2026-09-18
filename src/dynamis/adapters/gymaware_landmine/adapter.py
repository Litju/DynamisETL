"""GymAware landmine press anti-corruption adapter: source metrics only.

The verified archive contains no sample-level trajectory. This adapter therefore
imports exactly what the source distributes --- per-rep GymAware summary
indicators and the populated vision-workbook values --- as source-derived scalar
observations. No dense LPT stream, sample rate, displacement trace or time axis
is fabricated, and no correction (Deming, bias, scaling, smoothing) is applied.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from dynamis.adapters.gymaware_landmine import authorities
from dynamis.adapters.gymaware_landmine.discovery import (
    GymAwareDiscovery,
    GymAwareSet,
)
from dynamis.contracts import (
    AlgorithmKind,
    AlgorithmSpec,
    Device,
    MeasurementClass,
    ParticipantRole,
    Session,
    SessionKind,
    SessionParticipant,
    Subject,
    Trial,
)
from dynamis.pipeline.quarantine import (
    RULE_MISSING_PAIRING,
    RULE_NON_FINITE_VALUE,
    RULE_REQUIRED_FIELD_NULL,
    RULE_SCHEMA_FAILURE,
    QuarantinedRecord,
)
from dynamis.pipeline.source_metrics import SourceMetricObservation
from dynamis.pipeline.streams import ProviderDomain, SourceAuthorities

GYMAWARE_DATASET_ID = authorities.GYMAWARE_DATASET_ID

#: Source metric identifiers per method.
GYMAWARE_METRIC_IDS = {key: f"gymaware_{key}" for key in authorities.GYMAWARE_COLUMN_METRICS}
METRIC_UNITS = {
    "mean_velocity": "m/s",
    "peak_velocity": "m/s",
    "peak_power": "W",
    "mean_power": "W",
    "peak_force": "N",
    "mean_force": "N",
}

GYMAWARE_DEVICE_ID = "ga-gymaware-rs"
VISION_DEVICE_ID = "ga-vision-system"


def adapter_algorithm_spec() -> AlgorithmSpec:
    """Deterministic algorithm identity for the GymAware landmine importer."""
    return AlgorithmSpec(
        algorithm_id="gymaware_landmine_adapter",
        name="GymAware landmine press source-metric importer",
        version="1",
        kind=AlgorithmKind.ADAPTER,
        description=(
            "Imports per-rep GymAware summary indicators and the populated vision-workbook "
            "values as source-derived scalar metrics. No dense LPT stream exists in the "
            "archive and none is fabricated."
        ),
    )


@dataclass(frozen=True, slots=True)
class GymAwareTrial:
    trial_id: str
    subject_id: str
    session_id: str
    set_number: int
    rep_number: int
    activity: str | None
    load_kg: float | None
    load_source: str | None
    source_member: str
    source_member_sha256: str | None


@dataclass(slots=True)
class GymAwareCounters:
    source_sets: int = 0
    gymaware_sets: int = 0
    source_rep_rows: int = 0
    canonical_trials: int = 0
    vision_rows: int = 0
    vision_populated_values: int = 0
    quarantined_rep_rows: int = 0
    canonical_observations: int = 0
    quarantined_observations: int = 0
    quarantined: list[QuarantinedRecord] = field(default_factory=list)


def _trial_id(set_number: int, rep_number: int) -> str:
    return f"ga-t{set_number:03d}-r{int(rep_number):02d}"


def _subject_id(ordinal: int | None, set_number: int) -> str:
    if ordinal:
        return f"ga-p{ordinal:03d}"
    return f"ga-unresolved-{set_number:03d}"


def _session_id(subject_id: str) -> str:
    return f"session-{subject_id}"


class GymAwareAdapter:
    """Source-metric adapter over one decoded GymAware archive."""

    def __init__(self, discovery: GymAwareDiscovery) -> None:
        self._discovery = discovery
        self.counters = GymAwareCounters()
        self._vision_rows = {row.inclusion_number: row for row in discovery.vision.rows}
        self._sets: dict[int, GymAwareSet] = {}
        for item in discovery.gymaware_sets:
            self._sets[item.set_number] = item
        self._trials: dict[tuple[int, int], GymAwareTrial] = {}
        self._excluded_sets: dict[int, str] = {}
        self._hashes = discovery.structured_member_hashes
        self._observations: tuple[SourceMetricObservation, ...] | None = None
        self._build()

    @property
    def discovery(self) -> GymAwareDiscovery:
        return self._discovery

    @property
    def trials(self) -> tuple[GymAwareTrial, ...]:
        return tuple(self._trials[key] for key in sorted(self._trials))

    @property
    def excluded_sets(self) -> dict[int, str]:
        return dict(self._excluded_sets)

    def observations(self) -> tuple[SourceMetricObservation, ...]:
        """Source-metric observations, computed once (the import mutates counters)."""
        if self._observations is None:
            self._observations = (
                *self._gymaware_observations(),
                *self._vision_observations(),
            )
        return self._observations

    def domain(self) -> ProviderDomain:
        sessions: dict[str, Session] = {}
        subjects: dict[str, Subject] = {}
        participants: list[SessionParticipant] = []
        trials: list[Trial] = []
        for trial in self.trials:
            if trial.subject_id not in subjects:
                sessions[trial.session_id] = Session(
                    dataset_id=GYMAWARE_DATASET_ID,
                    session_id=trial.session_id,
                    kind=SessionKind.LABORATORY,
                    label=(
                        "Landmine press protocol; the source distributes no visit boundary, "
                        "so trials are grouped by source participant identity"
                    ),
                )
                subjects[trial.subject_id] = Subject(
                    dataset_id=GYMAWARE_DATASET_ID,
                    subject_id=trial.subject_id,
                    sex="unspecified",
                    cohort="landmine press protocol (GymAware + vision method comparison)",
                    notes=(
                        "pseudonymous identity derived from source workbook row order; "
                        "source display names are intentionally never persisted"
                    ),
                )
                participants.append(
                    SessionParticipant(
                        dataset_id=GYMAWARE_DATASET_ID,
                        session_id=trial.session_id,
                        subject_id=trial.subject_id,
                        role=ParticipantRole.PARTICIPANT,
                    )
                )
            trials.append(
                Trial(
                    dataset_id=GYMAWARE_DATASET_ID,
                    session_id=trial.session_id,
                    trial_id=trial.trial_id,
                    subject_id=trial.subject_id,
                    label=(
                        f"source_set={trial.set_number}; source_rep={trial.rep_number}; "
                        f"activity={trial.activity}; load_kg={trial.load_kg}"
                    ),
                )
            )
        return ProviderDomain(
            session=None,
            sessions=tuple(sessions.values()),
            subjects=tuple(subjects.values()),
            participants=tuple(participants),
            trials=tuple(trials),
            streams=(),
            authorities=SourceAuthorities(),
            devices=self.devices(),
            session_metadata={
                "source_key": authorities.VISION_WORKBOOK_KEY,
                "gymaware_csv_prefix": authorities.GYMAWARE_CSV_PREFIX,
                "measurement_class": MeasurementClass.SOURCE_DERIVED.value,
                "dense_lpt_stream_present": False,
                "vision_populated_values": self.counters.vision_populated_values,
                "excluded_sets": {
                    f"{number:03d}": reason
                    for number, reason in sorted(self._excluded_sets.items())
                },
                "method_metadata": {
                    "vision_effective_radius_m": authorities.VISION_EFFECTIVE_RADIUS_M,
                    "gymaware_effective_radius_m": authorities.GYMAWARE_EFFECTIVE_RADIUS_M,
                    "authority": authorities.RADIUS_AUTHORITY,
                    "correction_applied": False,
                },
            },
        )

    def devices(self) -> tuple[Device, ...]:
        return (
            Device(
                dataset_id=GYMAWARE_DATASET_ID,
                device_id=GYMAWARE_DEVICE_ID,
                device_type="linear_position_transducer",
                vendor="GymAware",
                model="RS",
                specs={
                    "effective_radius_m": authorities.GYMAWARE_EFFECTIVE_RADIUS_M,
                    "distributed_representation": "rep-level summary indicators only",
                    "sample_level_trajectory": False,
                },
            ),
            Device(
                dataset_id=GYMAWARE_DATASET_ID,
                device_id=VISION_DEVICE_ID,
                device_type="vision_tracking",
                vendor="source study vision pipeline",
                model="YOLO-based tracking (code included, outputs not distributed)",
                specs={
                    "effective_radius_m": authorities.VISION_EFFECTIVE_RADIUS_M,
                    "distributed_representation": "workbook values only where populated",
                    "sample_level_trajectory": False,
                },
            ),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _build(self) -> None:
        counters = self.counters
        numbered_sets = {item.set_number for item in self._discovery.gymaware_sets} | {
            row.inclusion_number for row in self._discovery.vision.rows
        }
        counters.source_sets = len(numbered_sets)
        counters.gymaware_sets = len(self._discovery.gymaware_sets)
        counters.vision_rows = len(self._discovery.vision.rows)
        counters.vision_populated_values = self._discovery.vision.populated_value_count
        for item in self._discovery.gymaware_sets:
            vision_row = self._vision_rows.get(item.set_number)
            subject_id = _subject_id(
                vision_row.subject_ordinal if vision_row else None, item.set_number
            )
            counters.source_rep_rows += item.source_rep_lines
            if item.malformed_rep_rows:
                counters.quarantined_rep_rows += item.malformed_rep_rows
                counters.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_SCHEMA_FAILURE,
                        detail="GymAware set export contains malformed rep rows",
                        dataset_id=GYMAWARE_DATASET_ID,
                        session_id=_session_id(subject_id),
                        subject_id=subject_id,
                        source_record_id=item.member_name,
                        evidence={
                            "source_rep_lines": item.source_rep_lines,
                            "parsed_rep_rows": len(item.reps),
                            "issues": list(item.issues),
                        },
                    )
                )
            if not item.reps:
                counters.quarantined.append(
                    QuarantinedRecord(
                        rule=RULE_SCHEMA_FAILURE,
                        detail="GymAware set export contains no usable rep rows",
                        dataset_id=GYMAWARE_DATASET_ID,
                        session_id=_session_id(subject_id),
                        stream_id=None,
                        subject_id=subject_id,
                        source_record_id=item.member_name,
                        evidence={"issues": list(item.issues)},
                    )
                )
                continue
            for rep in item.reps:
                if not math.isfinite(float(rep.rep_number)):
                    counters.quarantined_rep_rows += 1
                    counters.quarantined.append(
                        QuarantinedRecord(
                            rule=RULE_NON_FINITE_VALUE,
                            detail="rep number is not finite",
                            dataset_id=GYMAWARE_DATASET_ID,
                            session_id=_session_id(subject_id),
                            subject_id=subject_id,
                            source_record_id=f"{item.member_name}#{rep.rep_number}",
                            evidence={"rep_number": rep.rep_number},
                        )
                    )
                    continue
                load_kg = item.bar_weight_kg
                load_source = "gymaware_csv:bar weight (kg)"
                if load_kg is None and vision_row is not None:
                    load_kg = vision_row.load_kg
                    load_source = "vision_workbook:负重"
                trial = GymAwareTrial(
                    trial_id=_trial_id(item.set_number, int(rep.rep_number)),
                    subject_id=subject_id,
                    session_id=_session_id(subject_id),
                    set_number=item.set_number,
                    rep_number=int(rep.rep_number),
                    activity=vision_row.activity if vision_row else item.exercise,
                    load_kg=load_kg,
                    load_source=load_source,
                    source_member=item.member_name,
                    source_member_sha256=self._hashes.get(item.member_name),
                )
                if (item.set_number, int(rep.rep_number)) in self._trials:
                    counters.quarantined.append(
                        QuarantinedRecord(
                            rule=RULE_SCHEMA_FAILURE,
                            detail="duplicate GymAware rep identity in the archive",
                            dataset_id=GYMAWARE_DATASET_ID,
                            session_id=trial.session_id,
                            subject_id=subject_id,
                            source_record_id=f"{item.member_name}#{rep.rep_number}",
                            evidence={"trial_id": trial.trial_id},
                        )
                    )
                    counters.quarantined_rep_rows += 1
                    continue
                self._trials[(item.set_number, int(rep.rep_number))] = trial
                counters.canonical_trials += 1
        vision_inclusions = {row.inclusion_number for row in self._discovery.vision.rows}
        for number in sorted(vision_inclusions - set(self._sets)):
            self._excluded_sets[number] = (
                "vision workbook row present, but no GymAware set export and no numeric "
                "value distributed for any metric"
            )

    def _gymaware_observations(self) -> tuple[SourceMetricObservation, ...]:
        observations: list[SourceMetricObservation] = []
        for key in sorted(self._trials):
            trial = self._trials[key]
            item = self._sets[trial.set_number]
            rep = next(rep for rep in item.reps if int(rep.rep_number) == trial.rep_number)
            for field_name, metric_id in GYMAWARE_METRIC_IDS.items():
                value = rep.values.get(field_name)
                member_hash = trial.source_member_sha256 or ""
                if value is None:
                    self.counters.quarantined_observations += 1
                    self.counters.quarantined.append(
                        QuarantinedRecord(
                            rule=RULE_REQUIRED_FIELD_NULL,
                            detail=f"GymAware metric {field_name!r} is missing for this rep",
                            dataset_id=GYMAWARE_DATASET_ID,
                            session_id=trial.session_id,
                            subject_id=trial.subject_id,
                            source_record_id=f"{item.member_name}#{rep.rep_number}",
                            evidence={
                                "metric": metric_id,
                                "missing_fields": list(rep.missing_fields),
                            },
                        )
                    )
                    continue
                if not math.isfinite(value):
                    self.counters.quarantined_observations += 1
                    self.counters.quarantined.append(
                        QuarantinedRecord(
                            rule=RULE_NON_FINITE_VALUE,
                            detail=f"GymAware metric {field_name!r} is not finite",
                            dataset_id=GYMAWARE_DATASET_ID,
                            session_id=trial.session_id,
                            subject_id=trial.subject_id,
                            source_record_id=f"{item.member_name}#{rep.rep_number}",
                            evidence={"metric": metric_id, "value": repr(value)},
                        )
                    )
                    continue
                observations.append(
                    SourceMetricObservation(
                        dataset_id=GYMAWARE_DATASET_ID,
                        metric_id=metric_id,
                        name=_metric_name(metric_id),
                        si_unit=METRIC_UNITS[field_name],
                        measurement_class=MeasurementClass.SOURCE_DERIVED,
                        value=float(value),
                        source_field=f"GymAware CSV column for {field_name}",
                        source_key=item.member_name,
                        session_id=trial.session_id,
                        subject_id=trial.subject_id,
                        trial_id=trial.trial_id,
                        provenance={
                            "method": authorities.METHOD_GYMAWARE,
                            "method_radius_m": authorities.GYMAWARE_EFFECTIVE_RADIUS_M,
                            "radius_authority": authorities.RADIUS_AUTHORITY,
                            "source_member": item.member_name,
                            "source_member_sha256": member_hash,
                            "source_column_family": field_name,
                            "source_set_number": trial.set_number,
                            "source_rep_number": trial.rep_number,
                            "source_activity": trial.activity,
                            "load_kg": trial.load_kg,
                            "load_source": trial.load_source,
                            "cross_method_correction": (
                                "none (RES-98 preserves source measurements)"
                            ),
                        },
                    )
                )
                self.counters.canonical_observations += 1
        return tuple(observations)

    def _vision_observations(self) -> tuple[SourceMetricObservation, ...]:
        observations: list[SourceMetricObservation] = []
        workbook_hash = self._hashes.get(authorities.VISION_WORKBOOK_KEY, "")
        for row in self._discovery.vision.rows:
            if not any(
                any(value is not None for value in triple) for triple in row.values.values()
            ):
                continue
            for metric_id, triple in sorted(row.values.items()):
                for rep_index, value in enumerate(triple, start=1):
                    if value is None:
                        continue
                    trial = self._trials.get((row.inclusion_number, rep_index))
                    if trial is None:
                        self.counters.quarantined_observations += 1
                        self.counters.quarantined.append(
                            QuarantinedRecord(
                                rule=RULE_MISSING_PAIRING,
                                detail=(
                                    "vision workbook value has no paired GymAware rep in the "
                                    "verified archive"
                                ),
                                dataset_id=GYMAWARE_DATASET_ID,
                                session_id=_session_id(
                                    _subject_id(row.subject_ordinal, row.inclusion_number)
                                ),
                                subject_id=_subject_id(row.subject_ordinal, row.inclusion_number),
                                source_record_id=(
                                    f"{authorities.VISION_WORKBOOK_KEY}#"
                                    f"{row.inclusion_number}/REP{rep_index}"
                                ),
                                evidence={"metric": metric_id, "set_number": row.inclusion_number},
                            )
                        )
                        continue
                    field_name = metric_id.removeprefix("vision_")
                    if not math.isfinite(value):
                        self.counters.quarantined_observations += 1
                        self.counters.quarantined.append(
                            QuarantinedRecord(
                                rule=RULE_NON_FINITE_VALUE,
                                detail="vision workbook value is not finite",
                                dataset_id=GYMAWARE_DATASET_ID,
                                session_id=trial.session_id,
                                subject_id=trial.subject_id,
                                source_record_id=(
                                    f"{authorities.VISION_WORKBOOK_KEY}#"
                                    f"{row.inclusion_number}/REP{rep_index}"
                                ),
                                evidence={"metric": metric_id, "value": repr(value)},
                            )
                        )
                        continue
                    observations.append(
                        SourceMetricObservation(
                            dataset_id=GYMAWARE_DATASET_ID,
                            metric_id=metric_id,
                            name=_metric_name(metric_id),
                            si_unit=METRIC_UNITS[field_name],
                            measurement_class=MeasurementClass.SOURCE_DERIVED,
                            value=float(value),
                            source_field=(
                                f"{authorities.VISION_WORKBOOK_KEY} sheet for {field_name} "
                                f"REP{rep_index}"
                            ),
                            source_key=authorities.VISION_WORKBOOK_KEY,
                            session_id=trial.session_id,
                            subject_id=trial.subject_id,
                            trial_id=trial.trial_id,
                            provenance={
                                "method": authorities.METHOD_VISION,
                                "method_radius_m": authorities.VISION_EFFECTIVE_RADIUS_M,
                                "radius_authority": authorities.RADIUS_AUTHORITY,
                                "source_member": authorities.VISION_WORKBOOK_KEY,
                                "source_member_sha256": workbook_hash,
                                "source_column_family": field_name,
                                "source_set_number": row.inclusion_number,
                                "source_rep_number": rep_index,
                                "source_activity": row.activity,
                                "load_kg": row.load_kg,
                                "load_raw": row.load_raw,
                                "populated_row_scope": (
                                    "the verified workbook carries numeric values only for "
                                    "inclusion number 001"
                                ),
                                "independence_note": (
                                    "values are numerically identical to the GymAware export of "
                                    "the same set; the archive does not document an independent "
                                    "vision measurement for this row"
                                ),
                                "cross_method_correction": (
                                    "none (RES-98 preserves source measurements)"
                                ),
                            },
                        )
                    )
                    self.counters.canonical_observations += 1
        return tuple(observations)


def _metric_name(metric_id: str) -> str:
    for candidate_id, name, _unit in authorities.METRIC_DEFINITIONS:
        if candidate_id == metric_id:
            return name
    raise KeyError(metric_id)


def gymaware_algorithm_spec() -> AlgorithmSpec:
    return adapter_algorithm_spec()
