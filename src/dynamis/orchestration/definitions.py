"""Dagster Definitions for the DynamisData foundation (RES-96).

Load with::

    dagster dev -f src/dynamis/orchestration/definitions.py

Foundation assets plus the RES-97 real provider slices. The real-source assets
verify Bronze manifests and materialize canonical Silver streams; they never
fetch data and are only materialized when explicitly selected. Gold metrics
(RES-98+) and the visualization product are out of scope.
"""

from __future__ import annotations

from dagster import Definitions, load_assets_from_modules

from dynamis.orchestration import assets, real_sources

definitions = Definitions(
    assets=load_assets_from_modules([assets, real_sources]),
    asset_checks=[
        assets.synthetic_artifacts_are_zstd,
        assets.synthetic_roundtrip_reconciles,
        assets.registry_covers_all_modalities,
        real_sources.womens_gnss_reconciliation_balances,
        real_sources.dfl_tracking_reconciliation_balances,
    ],
)
