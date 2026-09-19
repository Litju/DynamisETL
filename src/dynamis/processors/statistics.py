"""Paired-comparison statistics with no automated scientific verdict.

Real paired comparisons in this repository are design-limited: a comparison can
report bias, MAE, RMSE, maximum absolute error, a Lin concordance correlation
coefficient and (only with a meaningful paired sample size) Bland-Altman limits.
It never emits a "valid"/"invalid" verdict, because agreement statistics alone
cannot establish method interchangeability.

Population (``ddof=0``) dispersion is used throughout so the numbers are exact
functions of the paired vectors and independent of library defaults.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """Descriptive agreement statistics for paired pipeline/reference values."""

    n: int
    bias: float
    mae: float
    rmse: float
    max_abs_error: float
    ccc: float | None
    tolerance: float | None = None
    within_tolerance: int | None = None
    pearson_r: float | None = None
    mean_pipeline: float | None = None
    mean_reference: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable agreement statistics."""
        payload: dict[str, Any] = {
            "n": self.n,
            "bias": self.bias,
            "mae": self.mae,
            "rmse": self.rmse,
            "max_abs_error": self.max_abs_error,
            "ccc": self.ccc,
            "pearson_r": self.pearson_r,
            "mean_pipeline": self.mean_pipeline,
            "mean_reference": self.mean_reference,
        }
        if self.tolerance is not None:
            payload["tolerance"] = self.tolerance
            payload["within_tolerance"] = self.within_tolerance
        payload.update(self.extra)
        return payload


def paired_comparison(
    pipeline: Any,
    reference: Any,
    *,
    tolerance: float | None = None,
) -> PairedComparison:
    """Compare two finite, equally long paired vectors.

    ``bias`` is ``mean(pipeline - reference)``, so a positive bias means the
    pipeline overestimates the reference. ``ccc`` is Lin's concordance
    correlation coefficient; it is ``None`` only when both vectors are constant
    and equal (a zero denominator), where it is undefined rather than zero.
    """
    a = np.asarray(pipeline, dtype=np.float64)
    b = np.asarray(reference, dtype=np.float64)
    if a.ndim != 1 or b.ndim != 1:
        raise ValueError("paired comparisons require one-dimensional vectors")
    if a.size != b.size:
        raise ValueError("paired comparisons require equal-length vectors")
    if a.size == 0:
        raise ValueError("paired comparisons require at least one pair")
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        raise ValueError("paired comparisons require finite values")
    diff = a - b
    bias = float(np.mean(diff))
    mae = float(np.mean(np.abs(diff)))
    rmse = float(np.sqrt(np.mean(diff**2)))
    max_abs = float(np.max(np.abs(diff)))
    var_a = float(np.var(a))
    var_b = float(np.var(b))
    cov = float(np.mean((a - a.mean()) * (b - b.mean())))
    ccc: float | None = None
    pearson: float | None = None
    denominator = var_a + var_b + (float(a.mean()) - float(b.mean())) ** 2
    if denominator > 0:
        ccc = 2.0 * cov / denominator
    if var_a > 0 and var_b > 0:
        pearson = cov / math.sqrt(var_a * var_b)
    within = None
    if tolerance is not None:
        within = int(np.count_nonzero(np.abs(diff) <= tolerance))
    return PairedComparison(
        n=int(a.size),
        bias=bias,
        mae=mae,
        rmse=rmse,
        max_abs_error=max_abs,
        ccc=ccc,
        tolerance=tolerance,
        within_tolerance=within,
        pearson_r=pearson,
        mean_pipeline=float(a.mean()),
        mean_reference=float(b.mean()),
    )


@dataclass(frozen=True, slots=True)
class BlandAltman:
    """Bias with symmetric limits of agreement at an explicit z quantile."""

    n: int
    mean_difference: float
    sd_difference: float
    lower_limit: float
    upper_limit: float
    z: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "mean_difference": self.mean_difference,
            "sd_difference": self.sd_difference,
            "lower_limit": self.lower_limit,
            "upper_limit": self.upper_limit,
            "z": self.z,
        }


def bland_altman(
    pipeline: Any,
    reference: Any,
    *,
    z: float = 1.96,
    min_pairs: int = 30,
) -> BlandAltman | None:
    """Limits of agreement, or ``None`` when the paired design is too small.

    A small or non-representative paired sample cannot support limits of
    agreement; the caller receives ``None`` instead of an overconfident band.
    """
    a = np.asarray(pipeline, dtype=np.float64)
    b = np.asarray(reference, dtype=np.float64)
    if a.size != b.size:
        raise ValueError("paired comparisons require equal-length vectors")
    if a.size < min_pairs or a.size < 2:
        return None
    diff = a - b
    mean_diff = float(np.mean(diff))
    sd_diff = float(np.std(diff))
    return BlandAltman(
        n=int(a.size),
        mean_difference=mean_diff,
        sd_difference=sd_diff,
        lower_limit=mean_diff - z * sd_diff,
        upper_limit=mean_diff + z * sd_diff,
        z=z,
    )


__all__ = ["BlandAltman", "PairedComparison", "bland_altman", "paired_comparison"]
