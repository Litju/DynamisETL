"""Women's Soccer Positioning anti-corruption adapter.

Provider: Zenodo record 10.5281/zenodo.10913119 (CC BY-NC 4.0).
Canonical target: ``gnss_sample`` streams, one per provider sheet (athlete).

The adapter never commits source rows: the workbook structure is discovered at
runtime (:mod:`dynamis.adapters.womens_soccer_positioning.discovery`) and the
mapping is enforced against that discovery.
"""

from dynamis.adapters.womens_soccer_positioning.adapter import (
    WOMENS_DATASET_ID,
    WOMENS_VERSION,
    WomenWorkbookAdapter,
    canonical_gnss_streams,
)

__all__ = [
    "WOMENS_DATASET_ID",
    "WOMENS_VERSION",
    "WomenWorkbookAdapter",
    "canonical_gnss_streams",
]
