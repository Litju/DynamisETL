"""GymAware landmine press + vision anti-corruption adapter.

Provider: Zenodo record 10.5281/zenodo.18598087 (v1; declared CC-BY-4.0,
attribution required, redistribution conditional, per the RES-104 rights
audit). The verified archive distributes rep-level summary indicators and
one populated vision-workbook example row; it contains no sample-level
trajectory. Canonical targets are source-derived scalar metric observations
only — no dense LPT stream is fabricated.

The ZIP container is untrusted external input: the central directory is
inspected and safety-gated before any member byte is read
(:mod:`dynamis.adapters.gymaware_landmine.zip_safety`).
"""

from dynamis.adapters.gymaware_landmine.adapter import (
    GYMAWARE_DATASET_ID,
    GymAwareAdapter,
    GymAwareTrial,
)

__all__ = ["GYMAWARE_DATASET_ID", "GymAwareAdapter", "GymAwareTrial"]
