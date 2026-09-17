"""DFL/Sportec IDSSE anti-corruption adapter.

Provider: Hugging Face ``pysport/idsse-data`` at a pinned commit revision
(CC BY 4.0). Canonical targets: ``tracking_sample`` streams (one per period,
multi-entity) and one ``event_record`` stream, plus match domain metadata.

The 372 MB positions XML is parsed with a bounded ``lxml.iterparse`` stream and
canonicalized frame-major; no full-source materialization is permitted.
"""

from dynamis.adapters.sportec_idsse.adapter import (
    IDSSE_DATASET_ID,
    IdsseMatchAdapter,
    IdsseMatchMetadata,
)

__all__ = ["IDSSE_DATASET_ID", "IdsseMatchAdapter", "IdsseMatchMetadata"]
