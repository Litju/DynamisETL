"""Clock and synchronization authorities.

Synchronization is a first-class contract, never a free-text annotation. A
stream either states how it was synchronized, with quantified residual
uncertainty, or it declares ``unknown`` and makes no accuracy claim at all.
"""

from __future__ import annotations

from pydantic import AwareDatetime, Field, model_validator

from dynamis.contracts.base import Contract, Identifier, NonNegativeFloat, PositiveFloat
from dynamis.contracts.enums import SynchronizationMethod, Timebase

_QUANTIFIED_METHODS = frozenset(
    {
        SynchronizationMethod.SOURCE_PROVIDED,
        SynchronizationMethod.HARDWARE_SYNCHRONIZED,
        SynchronizationMethod.EVENT_ALIGNED,
        SynchronizationMethod.CROSS_CORRELATION_ALIGNED,
        SynchronizationMethod.SOFTWARE_TIMESTAMPED,
    }
)


class Clock(Contract):
    """Declared timebase for ``t_rel_ns`` / ``timestamp_utc_ns`` columns."""

    clock_id: Identifier
    timebase: Timebase
    frequency_hz: PositiveFloat | None = None
    epoch_utc: AwareDatetime | None = None
    drift_ppm: float | None = None
    rollover_period_s: PositiveFloat | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check_clock(self) -> Clock:
        if self.timebase is Timebase.UNKNOWN and not (self.notes and self.notes.strip()):
            raise ValueError("an unknown timebase requires an explicit written justification")
        if self.timebase is Timebase.DEVICE_MONOTONIC and self.epoch_utc is not None:
            raise ValueError(
                "a device-monotonic clock has no meaningful UTC epoch; use gnss_utc or utc"
            )
        if self.timebase is Timebase.SESSION_MONOTONIC and self.epoch_utc is not None:
            raise ValueError("a session-monotonic clock is relative to the session origin")
        return self


class SynchronizationSpec(Contract):
    """How streams on one trial/session were placed on a common time axis."""

    sync_spec_id: Identifier
    method: SynchronizationMethod
    reference_clock_id: Identifier
    uncertainty_ms: NonNegativeFloat | None = None
    residual_max_abs_ms: NonNegativeFloat | None = None
    residual_rms_ms: NonNegativeFloat | None = None
    verified: bool = False
    verified_at: AwareDatetime | None = None
    evidence_artifact_id: Identifier | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def check_synchronization(self) -> SynchronizationSpec:
        quantified = (
            self.uncertainty_ms is not None
            or self.residual_max_abs_ms is not None
            or self.residual_rms_ms is not None
        )
        if self.method is SynchronizationMethod.UNKNOWN:
            if self.verified:
                raise ValueError("an unknown synchronization method cannot be marked verified")
            if quantified:
                raise ValueError(
                    "an unknown synchronization method cannot assert residual or uncertainty values"
                )
        elif self.method in _QUANTIFIED_METHODS and not quantified:
            if not (self.notes and self.notes.strip()):
                raise ValueError(
                    f"method {self.method.value!r} requires quantified uncertainty "
                    "(uncertainty_ms, residual_max_abs_ms or residual_rms_ms) "
                    "or an explicit written justification"
                )
        if self.verified and (self.verified_at is None or self.evidence_artifact_id is None):
            raise ValueError(
                "verified synchronization requires both verified_at and evidence_artifact_id"
            )
        if self.residual_max_abs_ms is not None and self.residual_rms_ms is not None:
            if self.residual_rms_ms > self.residual_max_abs_ms:
                raise ValueError("residual_rms_ms cannot exceed residual_max_abs_ms")
        return self


class SyncAlignment(Contract):
    """Optional explicit affine time alignment between two streams.

    ``t_target = t_source * scale + offset_ns``. Declared, never inferred, so an
    event-aligned or correlation-aligned offset is always auditable. The scale is
    always strictly positive and finite, and an alignment never pairs a stream
    with itself; a scale of 1 and an offset of 0 describe a shared released time
    coordinate, never an instrument-accuracy claim.
    """

    source_stream_id: Identifier
    target_stream_id: Identifier
    offset_ns: int
    scale: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    sync_spec_id: Identifier
    notes: str | None = None

    @model_validator(mode="after")
    def check_alignment(self) -> SyncAlignment:
        if self.source_stream_id == self.target_stream_id:
            raise ValueError("a sync alignment cannot pair a stream with itself")
        return self

    def apply(self, t_source_ns: int) -> int:
        return int(round(t_source_ns * self.scale + self.offset_ns))
