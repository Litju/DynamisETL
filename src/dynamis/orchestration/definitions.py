"""Dagster Definitions for the DynamisData foundation (RES-96).

Load with::

    dagster dev -f src/dynamis/orchestration/definitions.py

Only foundation assets exist here. Provider adapters (RES-97..RES-100), gold
metrics and the visualization product are out of scope.
"""

from __future__ import annotations

from dagster import Definitions, load_assets_from_modules

from dynamis.orchestration import assets

definitions = Definitions(
    assets=load_assets_from_modules([assets]),
    asset_checks=[
        assets.synthetic_artifacts_are_zstd,
        assets.synthetic_roundtrip_reconciles,
        assets.registry_covers_all_modalities,
    ],
)
