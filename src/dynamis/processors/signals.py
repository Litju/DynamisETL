"""Deterministic numeric kernels shared by every scientific processor.

Each kernel exposes its discretization and edge choices explicitly instead of
relying on a library default:

* integration is trapezoidal over an explicitly uniform timebase;
* derivatives use central differences with a named edge policy;
* rolling windows carry an explicit incomplete-edge policy;
* geodesy names its method and reference radius.

Processors compose these kernels; they never call an implicit filter, resample
or interpolate. No kernel silently fills a gap: a sample that cannot be computed
is ``NaN`` (and therefore excluded from scalar metrics by the caller) rather
than imputed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import signal as scipy_signal

#: Exact standard gravity, in m/s**2, used by force and IMU processors.
STANDARD_GRAVITY_M_S2 = 9.80665

NS_PER_SECOND = 1_000_000_000

#: IUGG mean Earth radius, in metres, for the explicit spherical geodesy method.
WGS84_MEAN_RADIUS_M = 6_371_008.8

#: One-sided first-order difference at the series edge.
EDGE_ONE_SIDED_FIRST_ORDER = "one_sided_first_order"
#: No value exists at the edge without extrapolation.
EDGE_NAN = "nan"
#: A window is only evaluated when it is fully inside the series.
EDGE_DROP_INCOMPLETE = "drop_incomplete"

DERIVATIVE_EDGE_POLICIES = (EDGE_ONE_SIDED_FIRST_ORDER, EDGE_NAN)
ROLLING_EDGE_POLICIES = (EDGE_DROP_INCOMPLETE,)

#: Explicit geodetic method identifiers. The spherical method is a documented
#: approximation, and the radius it uses is a parameter, not a hidden constant.
DISTANCE_METHOD_PLANAR = "planar_euclidean"
DISTANCE_METHOD_HAVERSINE = "haversine_wgs84_mean_radius"
ENU_METHOD_EQUIRECTANGULAR = "equirectangular_tangent_plane_wgs84_mean_radius"

FILTER_NONE = "none"
FILTER_BUTTERWORTH = "butterworth"
FILTER_FAMILIES = (FILTER_NONE, FILTER_BUTTERWORTH)

PHASE_ZERO_PHASE = "zero_phase"
PHASE_CAUSAL = "causal"
PHASES = (PHASE_ZERO_PHASE, PHASE_CAUSAL)

PADDING_ODD = "odd"
PADDING_EVEN = "even"
PADDING_CONSTANT = "constant"
PADDING_NONE = "none"
PADDINGS = (PADDING_ODD, PADDING_EVEN, PADDING_CONSTANT, PADDING_NONE)
_PADTYPE = {PADDING_ODD: "odd", PADDING_EVEN: "even", PADDING_CONSTANT: "constant"}


def _as_float_array(values: Any) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError("a signal must be one-dimensional")
    return array


def uniform_step_s(t_rel_ns: np.ndarray, *, tolerance_s: float = 1e-9) -> float:
    """Constant sample interval of a strictly increasing nanosecond time axis.

    A non-uniform or non-monotonic axis raises: the integrators and derivatives
    below document a uniform-step discretization, and silently accepting a
    different timebase would change their truncation error without recording it.
    """
    times = np.asarray(t_rel_ns, dtype=np.int64)
    if times.ndim != 1 or times.size < 2:
        raise ValueError("a uniform timebase requires at least two samples")
    steps = np.diff(times)
    if np.any(steps <= 0):
        raise ValueError("t_rel_ns must be strictly increasing within a stream")
    step_s = float(steps[0]) / NS_PER_SECOND
    if not np.allclose(steps.astype(np.float64), float(steps[0]), rtol=0.0, atol=0.0):
        if np.any(np.abs(steps.astype(np.float64) - float(steps[0])) > tolerance_s * 1e9):
            raise ValueError("t_rel_ns must advance by a constant step for this processor")
    return step_s


def cumulative_trapezoid(values: Any, step_s: float) -> np.ndarray:
    """Cumulative trapezoidal integral with ``y[0] = 0``.

    Trapezoidal error is ``O(f'' * h^2)`` per interval; a processor's tolerance
    must be justified against that order, not against a corpus maximum.
    """
    array = _as_float_array(values)
    if array.size == 0:
        return array.copy()
    if step_s <= 0:
        raise ValueError("step_s must be positive")
    result = np.empty_like(array)
    result[0] = 0.0
    if array.size > 1:
        result[1:] = np.cumsum((array[1:] + array[:-1]) * (0.5 * step_s))
    return result


def trapezoid_integral(values: Any, step_s: float) -> float:
    """Definite trapezoidal integral over the full series."""
    cumulative = cumulative_trapezoid(values, step_s)
    return float(cumulative[-1]) if cumulative.size else 0.0


def derivative(values: Any, step_s: float, *, edge_policy: str) -> np.ndarray:
    """Central-difference derivative with an explicit edge policy.

    Interior samples use the second-order central difference; the two edge
    samples follow ``edge_policy``:

    * ``one_sided_first_order``: first-order forward/backward difference;
    * ``nan``: no value is claimed at an edge that would require extrapolation.
    """
    array = _as_float_array(values)
    if edge_policy not in DERIVATIVE_EDGE_POLICIES:
        raise ValueError(f"unknown derivative edge policy {edge_policy!r}")
    if step_s <= 0:
        raise ValueError("step_s must be positive")
    result = np.full_like(array, np.nan)
    if array.size >= 2:
        result[1:-1] = (array[2:] - array[:-2]) / (2.0 * step_s)
        if edge_policy == EDGE_ONE_SIDED_FIRST_ORDER:
            result[0] = (array[1] - array[0]) / step_s
            result[-1] = (array[-1] - array[-2]) / step_s
    return result


def planar_speed(x_m: Any, y_m: Any, step_s: float, *, edge_policy: str) -> np.ndarray:
    """Planar speed from an explicit component-wise central difference."""
    vx = derivative(x_m, step_s, edge_policy=edge_policy)
    vy = derivative(y_m, step_s, edge_policy=edge_policy)
    return np.hypot(vx, vy)


def cumulative_planar_distance(x_m: Any, y_m: Any) -> np.ndarray:
    """Cumulative planar path length with ``distance[0] = 0``."""
    x = _as_float_array(x_m)
    y = _as_float_array(y_m)
    if x.size != y.size:
        raise ValueError("x and y must have the same length")
    if x.size == 0:
        return x.copy()
    steps = np.hypot(np.diff(x), np.diff(y))
    result = np.empty_like(x)
    result[0] = 0.0
    result[1:] = np.cumsum(steps)
    return result


def haversine_distance_m(
    latitude_deg: Any,
    longitude_deg: Any,
    *,
    radius_m: float = WGS84_MEAN_RADIUS_M,
) -> np.ndarray:
    """Step distances on a sphere of explicitly declared radius.

    The method is a documented approximation to the WGS 84 ellipsoid; it applies
    no datum transform and never reinterprets source coordinates.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    lat = np.radians(_as_float_array(latitude_deg))
    lon = np.radians(_as_float_array(longitude_deg))
    if lat.size != lon.size:
        raise ValueError("latitude and longitude must have the same length")
    if lat.size < 2:
        return np.zeros(0, dtype=np.float64)
    dlat = np.diff(lat)
    dlon = np.diff(lon)
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat[:-1]) * np.cos(lat[1:]) * np.sin(dlon / 2.0) ** 2
    return 2.0 * radius_m * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def enu_from_geodetic(
    latitude_deg: Any,
    longitude_deg: Any,
    *,
    origin_latitude_deg: float,
    origin_longitude_deg: float,
    radius_m: float = WGS84_MEAN_RADIUS_M,
) -> tuple[np.ndarray, np.ndarray]:
    """Local east/north tangent-plane projection with an explicit origin.

    The equirectangular tangent-plane approximation is exact at the origin,
    first-order accurate nearby and documented rather than hidden; it is used
    only to derive local velocities/accelerations, never to restate absolute
    positions as truth.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    lat = np.radians(_as_float_array(latitude_deg))
    lon = np.radians(_as_float_array(longitude_deg))
    if lat.size != lon.size:
        raise ValueError("latitude and longitude must have the same length")
    origin_lat = math.radians(origin_latitude_deg)
    origin_lon = math.radians(origin_longitude_deg)
    east = radius_m * (lon - origin_lon) * math.cos(origin_lat)
    north = radius_m * (lat - origin_lat)
    return east, north


def rolling_peak_window(
    cumulative: Any,
    time_s: Any,
    *,
    window_s: float,
    edge_policy: str = EDGE_DROP_INCOMPLETE,
) -> tuple[float, int]:
    """Maximum accumulated value over a sliding time window.

    ``cumulative`` must be non-decreasing (a cumulative distance or duration).
    ``drop_incomplete`` only evaluates windows fully contained in the series, so
    a short series reports no peak instead of extrapolating one. Returns
    ``(peak, end_index)``; an unevaluable series returns ``(nan, -1)``.
    """
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    if edge_policy not in ROLLING_EDGE_POLICIES:
        raise ValueError(f"unknown rolling edge policy {edge_policy!r}")
    cumulative_values = _as_float_array(cumulative)
    times = _as_float_array(time_s)
    if cumulative_values.size != times.size:
        raise ValueError("cumulative and time arrays must have the same length")
    if cumulative_values.size < 2:
        return float("nan"), -1
    if not np.all(np.diff(cumulative_values) >= 0):
        raise ValueError("cumulative values must be non-decreasing")
    peak = float("nan")
    peak_index = -1
    start = 0
    for end in range(1, times.size):
        while times[end] - times[start] > window_s:
            start += 1
        if edge_policy == EDGE_DROP_INCOMPLETE and times[end] - times[0] < window_s:
            continue
        covered = float(cumulative_values[end] - cumulative_values[start])
        if not math.isfinite(peak) or covered > peak:
            peak = covered
            peak_index = end
    return peak, peak_index


def zone_statistics(
    speed_m_s: Any,
    distance_step_m: Any,
    *,
    zones: tuple[SpeedZone, ...],
    step_s: float,
) -> dict[str, dict[str, float]]:
    """Distance, duration and peak speed per explicitly supplied zone."""
    speed = _as_float_array(speed_m_s)
    steps = _as_float_array(distance_step_m)
    if speed.size != steps.size:
        raise ValueError("speed and distance_step arrays must have the same length")
    result: dict[str, dict[str, float]] = {}
    for zone in zones:
        inside = zone.mask(speed)
        count = int(np.count_nonzero(inside))
        distance = float(np.sum(steps[inside])) if count else 0.0
        peak = float(np.max(speed[inside])) if count else 0.0
        result[zone.name] = {
            "distance_m": distance,
            "duration_s": count * step_s,
            "peak_speed_m_s": peak,
            "samples": float(count),
        }
    return result


@dataclass(frozen=True, slots=True)
class SpeedZone:
    """One explicit speed zone in SI units (supplied configuration)."""

    name: str
    lower_m_s: float
    upper_m_s: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a speed zone requires a name")
        if not math.isfinite(self.lower_m_s) or self.lower_m_s < 0:
            raise ValueError("zone lower bound must be finite and non-negative")
        if self.upper_m_s is not None:
            if not math.isfinite(self.upper_m_s) or self.upper_m_s <= self.lower_m_s:
                raise ValueError("zone upper bound must be finite and above the lower bound")

    def mask(self, speed_m_s: np.ndarray) -> np.ndarray:
        inside = speed_m_s >= self.lower_m_s
        if self.upper_m_s is not None:
            inside = inside & (speed_m_s < self.upper_m_s)
        return inside

    def parameters(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "lower_m_s": self.lower_m_s,
            "upper_m_s": self.upper_m_s,
        }

    @staticmethod
    def from_parameters(parameters: dict[str, Any]) -> SpeedZone:
        return SpeedZone(
            name=str(parameters["name"]),
            lower_m_s=float(parameters["lower_m_s"]),
            upper_m_s=None
            if parameters.get("upper_m_s") is None
            else float(parameters["upper_m_s"]),
        )


@dataclass(frozen=True, slots=True)
class Effort:
    """One contiguous above-threshold effort, in sample indices (inclusive)."""

    start_index: int
    end_index: int
    duration_s: float
    peak_speed_m_s: float
    distance_m: float


@dataclass(frozen=True, slots=True)
class EffortParameters:
    """Explicit effort-segmentation configuration."""

    threshold_m_s: float
    min_duration_s: float
    merge_gap_s: float = 0.0
    hysteresis_m_s: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.threshold_m_s) or self.threshold_m_s < 0:
            raise ValueError("effort threshold must be finite and non-negative")
        if not math.isfinite(self.min_duration_s) or self.min_duration_s < 0:
            raise ValueError("effort minimum duration must be finite and non-negative")
        if not math.isfinite(self.merge_gap_s) or self.merge_gap_s < 0:
            raise ValueError("effort merge gap must be finite and non-negative")
        if not math.isfinite(self.hysteresis_m_s) or self.hysteresis_m_s < 0:
            raise ValueError("effort hysteresis must be finite and non-negative")

    def parameters(self) -> dict[str, Any]:
        return {
            "threshold_m_s": self.threshold_m_s,
            "min_duration_s": self.min_duration_s,
            "merge_gap_s": self.merge_gap_s,
            "hysteresis_m_s": self.hysteresis_m_s,
        }


def effort_segments(
    speed_m_s: Any,
    distance_step_m: Any,
    *,
    step_s: float,
    parameters: EffortParameters,
) -> tuple[Effort, ...]:
    """Segment efforts with explicit threshold, duration, gap and hysteresis.

    A sample enters an effort at ``speed >= threshold`` and leaves it below
    ``threshold - hysteresis``. Candidate runs separated by no more than
    ``merge_gap_s`` merge; a merged run shorter than ``min_duration_s`` is
    discarded. Every choice is a supplied parameter, never a sport constant.
    """
    speed = _as_float_array(speed_m_s)
    steps = _as_float_array(distance_step_m)
    if speed.size != steps.size:
        raise ValueError("speed and distance_step arrays must have the same length")
    active = parameters.threshold_m_s
    release = max(0.0, parameters.threshold_m_s - parameters.hysteresis_m_s)
    runs: list[list[int]] = []
    state = False
    start = 0
    for index, value in enumerate(speed):
        if not state and value >= active:
            state = True
            start = index
        elif state and value < release:
            runs.append([start, index - 1])
            state = False
    if state and speed.size:
        runs.append([start, speed.size - 1])
    merged: list[list[int]] = []
    max_gap_samples = parameters.merge_gap_s / step_s if step_s > 0 else 0.0
    for run in runs:
        if merged and (run[0] - merged[-1][1] - 1) <= max_gap_samples:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    efforts: list[Effort] = []
    for begin, end in merged:
        duration = (end - begin + 1) * step_s
        if duration + 1e-12 < parameters.min_duration_s:
            continue
        window_speed = speed[begin : end + 1]
        window_steps = steps[begin : end + 1]
        efforts.append(
            Effort(
                start_index=begin,
                end_index=end,
                duration_s=float(duration),
                peak_speed_m_s=float(np.max(window_speed)) if window_speed.size else 0.0,
                distance_m=float(np.sum(window_steps)),
            )
        )
    return tuple(efforts)


@dataclass(frozen=True, slots=True)
class FilterSpec:
    """Fully explicit filter configuration; ``none`` means no filtering at all."""

    family: str = FILTER_NONE
    order: int | None = None
    cutoff_hz: float | None = None
    phase: str = PHASE_ZERO_PHASE
    padding: str = PADDING_ODD
    padlen: int | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if self.family not in FILTER_FAMILIES:
            raise ValueError(f"unknown filter family {self.family!r}")
        if self.phase not in PHASES:
            raise ValueError(f"unknown filter phase {self.phase!r}")
        if self.padding not in PADDINGS:
            raise ValueError(f"unknown filter padding {self.padding!r}")
        if self.family == FILTER_NONE:
            if self.order is not None or self.cutoff_hz is not None:
                raise ValueError("filter family 'none' must not declare order or cutoff")
        else:
            if self.order is None or self.order < 1:
                raise ValueError("butterworth filtering requires a positive order")
            if self.cutoff_hz is None or not math.isfinite(self.cutoff_hz) or self.cutoff_hz <= 0:
                raise ValueError("butterworth filtering requires a positive cutoff")
        if self.padlen is not None and self.padlen < 0:
            raise ValueError("padlen must be non-negative when supplied")

    def parameters(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "order": self.order,
            "cutoff_hz": self.cutoff_hz,
            "phase": self.phase,
            "padding": self.padding,
            "padlen": self.padlen,
        }

    @staticmethod
    def from_parameters(parameters: dict[str, Any] | None) -> FilterSpec:
        if parameters is None:
            return FilterSpec()
        return FilterSpec(
            family=str(parameters.get("family", FILTER_NONE)),
            order=None if parameters.get("order") is None else int(parameters["order"]),
            cutoff_hz=(
                None if parameters.get("cutoff_hz") is None else float(parameters["cutoff_hz"])
            ),
            phase=str(parameters.get("phase", PHASE_ZERO_PHASE)),
            padding=str(parameters.get("padding", PADDING_ODD)),
            padlen=None if parameters.get("padlen") is None else int(parameters["padlen"]),
            description=str(parameters.get("description", "")),
        )

    def apply(self, values: Any, *, rate_hz: float) -> np.ndarray:
        """Apply the configured filter, or return an untouched copy for ``none``."""
        array = _as_float_array(values)
        if self.family == FILTER_NONE:
            return array.copy()
        if rate_hz <= 0:
            raise ValueError("a filter requires a positive sampling rate")
        if self.cutoff_hz is None or self.cutoff_hz >= rate_hz / 2.0:
            raise ValueError(
                f"cutoff {self.cutoff_hz} Hz must be below the {rate_hz / 2.0:g} Hz Nyquist "
                "frequency"
            )
        assert self.order is not None
        sos = scipy_signal.butter(self.order, self.cutoff_hz, btype="low", fs=rate_hz, output="sos")
        if self.phase == PHASE_CAUSAL:
            return np.asarray(scipy_signal.sosfilt(sos, array), dtype=np.float64)
        padtype = _PADTYPE.get(self.padding)
        kwargs: dict[str, Any] = {"padtype": padtype}
        if self.padlen is not None:
            kwargs["padlen"] = self.padlen
        return np.asarray(scipy_signal.sosfiltfilt(sos, array, **kwargs), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class DerivativeSpec:
    """Explicit derivative configuration: filter (or none) then edge policy."""

    filter: FilterSpec = field(default_factory=FilterSpec)
    edge_policy: str = EDGE_NAN

    def __post_init__(self) -> None:
        if self.edge_policy not in DERIVATIVE_EDGE_POLICIES:
            raise ValueError(f"unknown derivative edge policy {self.edge_policy!r}")

    def parameters(self) -> dict[str, Any]:
        return {
            "filter": self.filter.parameters(),
            "edge_policy": self.edge_policy,
        }
