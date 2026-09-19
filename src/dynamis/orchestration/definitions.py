"""Dagster Definitions for the DynamisData platform.

Load with::

    dagster dev -f src/dynamis/orchestration/definitions.py

Foundation assets plus the RES-97 real provider slices, the RES-98 laboratory
slices and the RES-100 processor/Gold lineage. Importing these definitions never
downloads anything and never touches scientific data; real-source and processor
assets only run when explicitly selected, and CI materializes the synthetic
foundation and the synthetic LPT known-answer asset only.
"""

from __future__ import annotations

from dagster import Definitions, load_assets_from_modules

from dynamis.orchestration import assets, lab_sources, processors, real_sources

definitions = Definitions(
    assets=load_assets_from_modules([assets, real_sources, lab_sources, processors]),
    asset_checks=[
        assets.synthetic_artifacts_are_zstd,
        assets.synthetic_roundtrip_reconciles,
        assets.registry_covers_all_modalities,
        real_sources.womens_gnss_reconciliation_balances,
        real_sources.dfl_tracking_reconciliation_balances,
        lab_sources.white_cmj_reconciliation_balances,
        lab_sources.gymaware_landmine_reconciliation_balances,
        processors.white_force_processing_complete,
        processors.gold_marts_reconcile,
        processors.synthetic_lpt_known_answer_holds,
    ],
)
