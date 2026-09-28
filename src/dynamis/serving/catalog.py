"""Metadata-only semantic catalog projection and product routing."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from dynamis.adapters.sportsdataverse.ingest import LEAGUES as SPORTSDATAVERSE_LEAGUES
from dynamis.adapters.sportsdataverse.taxonomy import (
    FAMILY_CAPABILITIES,
)
from dynamis.adapters.sportsdataverse.taxonomy import (
    edition_label as sportsdataverse_edition_label,
)
from dynamis.contracts.sports import (
    Capability,
    DataGrainKind,
    SportsEntityKind,
    canonical_sports_id,
    derive_capability_profile,
    route_products,
)
from dynamis.serving.models import (
    CatalogReadModelView,
    CatalogResourceView,
    CatalogStageView,
    DatasetSummary,
    GameEditionView,
    ProductRouteView,
    SeasonEditionView,
    SessionDetail,
    SourceCapabilityView,
    SportsCatalogMatchView,
)

_ACTION_BY_STATE = {
    "UPSTREAM_AVAILABLE": "register",
    "REGISTERED": "acquire",
    "ACQUISITION_FAILED": "acquire",
    "ACQUIRED": "materialize",
    "MATERIALIZATION_FAILED": "materialize",
    "MATERIALIZED": "validate",
    "VALIDATION_FAILED": "validate",
}
_STAGE_ORDER = {
    None: 0,
    "UPSTREAM_AVAILABLE": 1,
    "REGISTERED": 2,
    "ACQUISITION_FAILED": 2,
    "ACQUIRED": 3,
    "MATERIALIZATION_FAILED": 3,
    "MATERIALIZED": 4,
    "VALIDATION_FAILED": 4,
    "READY": 5,
}
_MODALITY_CAPABILITIES = {
    "force": Capability.FORCE,
    "imu": Capability.IMU,
    "lpt": Capability.LPT,
    "gnss": Capability.GNSS,
    "tracking": Capability.TRACKING,
    "pose": Capability.POSE,
    "event": Capability.EVENTS,
}


def _capabilities(names: Sequence[str]) -> list[Capability]:
    return [Capability(name) for name in names if name in Capability._value2member_map_]


def _routes(
    upstream: Sequence[str],
    registered: Sequence[str],
    materialized: Sequence[str],
    grains: Sequence[str],
    products: set[str] | None = None,
) -> list[ProductRouteView]:
    profile = derive_capability_profile(
        upstream=(
            (capability, f"upstream:{capability.value}") for capability in _capabilities(upstream)
        ),
        registered=(
            (capability, f"registered:{capability.value}")
            for capability in _capabilities(registered)
        ),
        materialized=(
            (capability, f"materialized:{capability.value}")
            for capability in _capabilities(materialized)
        ),
    )
    kinds = [DataGrainKind(grain) for grain in grains if grain in DataGrainKind._value2member_map_]
    routes = [
        ProductRouteView(
            product=route.product.value,
            ready=route.ready,
            missing_capabilities=[
                [capability.value for capability in alternative]
                for alternative in route.missing_capabilities
            ],
            missing_grains=[
                [grain.value for grain in alternative] for alternative in route.missing_grains
            ],
        )
        for route in route_products(profile, kinds)
    ]
    return [route for route in routes if products is None or route.product in products]


def _stages(
    *,
    upstream: Sequence[str],
    registered: Sequence[str],
    materialized: Sequence[str],
    routes: Sequence[ProductRouteView],
    state: str | None,
    source_known: bool,
) -> CatalogStageView:
    registered_states = {
        "REGISTERED",
        "ACQUIRED",
        "MATERIALIZATION_FAILED",
        "MATERIALIZED",
        "VALIDATION_FAILED",
        "READY",
    }
    materialized_states = {
        "ACQUIRED",
        "MATERIALIZATION_FAILED",
        "MATERIALIZED",
        "VALIDATION_FAILED",
        "READY",
    }
    ready = any(route.ready for route in routes)
    return CatalogStageView(
        upstream="available" if source_known or upstream else "unavailable",
        registered="registered" if registered or state in registered_states else "not_registered",
        materialized=(
            "materialized" if materialized or state in materialized_states else "not_materialized"
        ),
        ready="ready" if ready else "not_ready",
    )


def _state(states: Sequence[str]) -> str | None:
    return max(states, key=lambda item: _STAGE_ORDER.get(item, 0), default=None)


def _actions(states: Sequence[str]) -> list[str]:
    return sorted({_ACTION_BY_STATE[state] for state in states if state in _ACTION_BY_STATE})


def _rights(
    dataset_ids: Sequence[str], datasets: Mapping[str, DatasetSummary]
) -> tuple[list[str], bool, bool]:
    policies = [datasets[item].license for item in dataset_ids if item in datasets]
    return (
        sorted({policy.identifier for policy in policies if policy.identifier}),
        any(policy.noncommercial_only for policy in policies),
        any(policy.local_only for policy in policies),
    )


def _edition_entry(
    editions: dict[str, dict[str, Any]],
    *,
    edition_id: str,
    edition_label: str,
    sport_id: str,
    sport_name: str,
    competition_id: str,
    competition_name: str,
) -> dict[str, Any]:
    entry = editions.get(edition_id)
    if entry is None:
        entry = {
            "resource_id": edition_id,
            "label": edition_label,
            "sport_id": sport_id,
            "sport_name": sport_name,
            "competition_id": competition_id,
            "competition_name": competition_name,
            "edition_id": edition_id,
            "edition_label": edition_label,
            "dataset_ids": set(),
            "providers": set(),
            "source_entry_ids": set(),
            "external_ids": set(),
            "availability_states": [],
            "upstream": set(),
            "registered": set(),
            "materialized": set(),
            "grains": set(),
            "source_known": False,
        }
        editions[edition_id] = entry
    elif entry["sport_id"] != sport_id or entry["competition_id"] != competition_id:
        raise ValueError(f"canonical edition {edition_id!r} has conflicting semantic parents")
    return entry


def _add_source_capability(
    entry: dict[str, Any], dataset_id: str, item: SourceCapabilityView
) -> None:
    entry["dataset_ids"].add(dataset_id)
    entry["providers"].add(item.provider)
    entry["source_entry_ids"].add(item.entry_id)
    entry["external_ids"].add(item.external_id)
    entry["availability_states"].append(item.availability_state)
    entry["upstream"].update(item.upstream_capabilities)
    entry["registered"].update(item.registered_capabilities)
    entry["materialized"].update(item.materialized_capabilities or item.local_capabilities)
    entry["grains"].update(item.materialized_grains)
    entry["source_known"] = True


def _edition_resource(
    entry: dict[str, Any], datasets: Mapping[str, DatasetSummary]
) -> CatalogResourceView:
    upstream = sorted(entry["upstream"])
    registered = sorted(entry["registered"])
    materialized = sorted(entry["materialized"])
    grains = sorted(entry["grains"])
    routes = _routes(upstream, registered, materialized, grains, {"GameLab", "SeasonLab"})
    state = _state(entry["availability_states"])
    rights, noncommercial_only, local_only = _rights(sorted(entry["dataset_ids"]), datasets)
    return CatalogResourceView(
        resource_kind="competition_edition",
        resource_id=entry["resource_id"],
        label=entry["label"],
        dataset_ids=sorted(entry["dataset_ids"]),
        providers=sorted(entry["providers"]),
        source_entry_ids=sorted(entry["source_entry_ids"]),
        external_ids=sorted(entry["external_ids"]),
        sport_id=entry["sport_id"],
        sport_name=entry["sport_name"],
        competition_id=entry["competition_id"],
        competition_name=entry["competition_name"],
        edition_id=entry["edition_id"],
        edition_label=entry["edition_label"],
        rights_identifiers=rights,
        noncommercial_only=noncommercial_only,
        local_only=local_only,
        availability_state=state,
        stages=_stages(
            upstream=upstream,
            registered=registered,
            materialized=materialized,
            routes=routes,
            state=state,
            source_known=entry["source_known"],
        ),
        upstream_capabilities=upstream,
        registered_capabilities=registered,
        materialized_capabilities=materialized,
        materialized_grains=grains,
        routes=routes,
        preparation_eligible=bool(_actions(entry["availability_states"])),
        preparation_actions=_actions(entry["availability_states"]),
    )


def _snapshot_editions(
    editions: dict[str, dict[str, Any]],
    snapshot: Mapping[str, Any] | None,
    datasets: Mapping[str, DatasetSummary],
) -> None:
    if snapshot is None:
        return
    specs = {item.league_id: item for item in SPORTSDATAVERSE_LEAGUES.values()}
    source = datasets.get("sportsdataverse")
    if source is None:
        return
    for family in snapshot["families"]:
        league_id = family.get("league_id")
        spec = specs.get(league_id)
        if spec is None or league_id not in {"nba", "nhl"}:
            continue
        for _, season, _, asset_id in family["parquet_assets"]:
            edition_id = canonical_sports_id(spec.namespace, SportsEntityKind.EDITION, str(season))
            competition_id = canonical_sports_id(
                spec.namespace, SportsEntityKind.COMPETITION, spec.league_id
            )
            entry = _edition_entry(
                editions,
                edition_id=edition_id,
                edition_label=sportsdataverse_edition_label(spec.league_id, int(season)),
                sport_id=spec.sport_id,
                sport_name=spec.sport_name,
                competition_id=competition_id,
                competition_name=spec.competition_name,
            )
            entry["dataset_ids"].add(source.dataset_id)
            entry["providers"].add("SportsDataverse")
            entry["external_ids"].add(f"{family['tag']}/{asset_id}")
            entry["availability_states"].append("UPSTREAM_AVAILABLE")
            entry["upstream"].update(FAMILY_CAPABILITIES.get(family["family_kind"], ()))
            entry["source_known"] = True


def build_catalog_read_model(
    *,
    datasets: Sequence[DatasetSummary],
    matches: Sequence[SportsCatalogMatchView],
    game_editions: Sequence[GameEditionView],
    season_editions: Sequence[SeasonEditionView],
    source_capabilities: Mapping[str, Sequence[SourceCapabilityView]],
    performance_sessions: Sequence[tuple[DatasetSummary, SessionDetail]],
    sportsdataverse_snapshot: Mapping[str, Any] | None = None,
) -> CatalogReadModelView:
    """Join only explicit canonical IDs and publish deterministic product gates."""
    dataset_by_id = {dataset.dataset_id: dataset for dataset in datasets}
    editions: dict[str, dict[str, Any]] = {}

    for edition in [*game_editions, *season_editions]:
        entry = _edition_entry(
            editions,
            edition_id=edition.edition_id,
            edition_label=edition.edition_label,
            sport_id=edition.sport_id,
            sport_name=edition.sport_name,
            competition_id=edition.competition_id,
            competition_name=edition.competition_name,
        )
        entry["dataset_ids"].add(edition.dataset_id)
        entry["providers"].add(edition.provider)
        entry["source_known"] = True
        if isinstance(edition, GameEditionView):
            for family in edition.families:
                if family.grain_kind in DataGrainKind._value2member_map_:
                    entry["grains"].add(family.grain_kind)
                if family.grain_kind == DataGrainKind.PLAY_BY_PLAY.value:
                    entry["materialized"].add(Capability.PLAY_BY_PLAY.value)
                elif family.grain_kind == DataGrainKind.EVENT_SERIES.value:
                    entry["materialized"].add(Capability.EVENTS.value)
                elif family.grain_kind in {
                    DataGrainKind.PLAYER_GAME.value,
                    DataGrainKind.TEAM_GAME.value,
                }:
                    entry["materialized"].add(Capability.BOX_SCORE.value)
                entry["availability_states"].append("MATERIALIZED")
        else:
            for family in edition.families:
                if family.grain_kind in DataGrainKind._value2member_map_:
                    entry["grains"].add(family.grain_kind)
                entry["materialized"].add(Capability.SEASON_AGGREGATE.value)
                entry["availability_states"].append("MATERIALIZED")

    for dataset_id, items in source_capabilities.items():
        for item in items:
            if not item.edition_id or not item.competition_id or not item.sport_id:
                continue
            entry = _edition_entry(
                editions,
                edition_id=item.edition_id,
                edition_label=item.edition_label or item.edition_id,
                sport_id=item.sport_id,
                sport_name=item.sport_name or item.sport_id,
                competition_id=item.competition_id,
                competition_name=item.competition_name or item.competition_id,
            )
            _add_source_capability(entry, dataset_id, item)

    _snapshot_editions(editions, sportsdataverse_snapshot, dataset_by_id)
    resources = [_edition_resource(entry, dataset_by_id) for entry in editions.values()]

    for match in matches:
        capability = match.source_capability
        match_upstream = capability.upstream_capabilities if capability else []
        match_registered = capability.registered_capabilities if capability else []
        match_materialized = (
            (capability.materialized_capabilities or capability.local_capabilities)
            if capability
            else []
        )
        match_grains = capability.materialized_grains if capability else []
        routes = _routes(
            match_upstream,
            match_registered,
            match_materialized,
            match_grains,
            {"MatchLab", "GameLab"},
        )
        state = capability.availability_state if capability else None
        provider = (
            capability.provider
            if capability
            else (
                dataset_by_id[match.dataset_id].provider
                if match.dataset_id in dataset_by_id
                else ""
            )
        )
        rights, noncommercial_only, local_only = _rights([match.dataset_id], dataset_by_id)
        resources.append(
            CatalogResourceView(
                resource_kind="contest",
                resource_id=match.contest_id,
                label=match.label or f"Contest {match.provider_match_id}",
                dataset_ids=[match.dataset_id],
                providers=[provider] if provider else [],
                source_entry_ids=[capability.entry_id] if capability else [],
                external_ids=[match.provider_match_id],
                sport_id=match.sport_id,
                sport_name=match.sport_name,
                competition_id=match.competition_id,
                competition_name=match.competition_name,
                edition_id=match.edition_id,
                edition_label=match.edition_label,
                contest_id=match.contest_id,
                teams=match.teams,
                session_id=match.session_id,
                rights_identifiers=rights,
                noncommercial_only=noncommercial_only,
                local_only=local_only,
                availability_state=state,
                stages=_stages(
                    upstream=match_upstream,
                    registered=match_registered,
                    materialized=match_materialized,
                    routes=routes,
                    state=state,
                    source_known=capability is not None,
                ),
                upstream_capabilities=sorted(set(match_upstream)),
                registered_capabilities=sorted(set(match_registered)),
                materialized_capabilities=sorted(set(match_materialized)),
                materialized_grains=sorted(set(match_grains)),
                routes=routes,
                basketball_spatial_ready=(
                    match.sport_id == "basketball"
                    and Capability.TRACKING.value in match_materialized
                    and DataGrainKind.FRAME_SERIES.value in match_grains
                ),
                preparation_eligible=bool(capability and capability.preparation_eligible),
                preparation_actions=(
                    [capability.preparation_action]
                    if capability and capability.preparation_action
                    else []
                ),
            )
        )

    capabilities_by_dataset: dict[str, list[SourceCapabilityView]] = defaultdict(list)
    for dataset_id, items in source_capabilities.items():
        capabilities_by_dataset[dataset_id].extend(items)
    datasets_with_sessions = {dataset.dataset_id for dataset, _ in performance_sessions}
    for dataset in datasets:
        if dataset.domain != "laboratory" or dataset.dataset_id in datasets_with_sessions:
            continue
        source_items = capabilities_by_dataset.get(dataset.dataset_id, [])
        upstream = {
            capability.value
            for modality in dataset.modalities
            if (capability := _MODALITY_CAPABILITIES.get(modality)) is not None
        }
        for item in source_items:
            upstream.update(item.upstream_capabilities)
        registered = {
            capability.value
            for modality in dataset.ingested_modalities
            if (capability := _MODALITY_CAPABILITIES.get(modality)) is not None
        }
        upstream_list = sorted(upstream)
        registered_list = sorted(registered)
        routes = _routes(upstream_list, registered_list, [], [], {"PerformanceLab"})
        states = [item.availability_state for item in source_items]
        state = _state(states) or (
            "REGISTERED" if registered_list else "UPSTREAM_AVAILABLE" if upstream_list else None
        )
        actions = _actions(states)
        if not actions and registered_list:
            actions = ["materialize"]
        elif not actions and upstream_list:
            actions = ["register"]
        rights, noncommercial_only, local_only = _rights([dataset.dataset_id], dataset_by_id)
        resources.append(
            CatalogResourceView(
                resource_kind="performance_dataset",
                resource_id=dataset.dataset_id,
                label=dataset.name,
                dataset_ids=[dataset.dataset_id],
                providers=[dataset.provider],
                source_entry_ids=[item.entry_id for item in source_items],
                external_ids=[item.external_id for item in source_items],
                rights_identifiers=rights,
                noncommercial_only=noncommercial_only,
                local_only=local_only,
                availability_state=state,
                stages=_stages(
                    upstream=upstream_list,
                    registered=registered_list,
                    materialized=[],
                    routes=routes,
                    state=state,
                    source_known=bool(dataset.upstream_urls),
                ),
                upstream_capabilities=upstream_list,
                registered_capabilities=registered_list,
                routes=routes,
                preparation_eligible=bool(actions),
                preparation_actions=actions,
            )
        )
    for dataset, detail in performance_sessions:
        source_items = capabilities_by_dataset.get(dataset.dataset_id, [])
        upstream = {
            capability.value
            for modality in dataset.modalities
            if (capability := _MODALITY_CAPABILITIES.get(modality)) is not None
        }
        for item in source_items:
            upstream.update(item.upstream_capabilities)
        registered: set[str] = set()
        materialized: set[str] = set()
        grains: set[str] = set()
        for stream in detail.streams:
            capability = _MODALITY_CAPABILITIES.get(stream.modality)
            if capability is not None:
                registered.add(capability.value)
                if stream.sample_artifact_ids:
                    materialized.add(capability.value)
            grain = stream.data_grain_kind
            if stream.sample_artifact_ids and grain in DataGrainKind._value2member_map_:
                assert grain is not None
                grains.add(grain)
        upstream_list = sorted(upstream)
        registered_list = sorted(registered)
        materialized_list = sorted(materialized)
        grain_list = sorted(grains)
        routes = _routes(
            upstream_list,
            registered_list,
            materialized_list,
            grain_list,
            {"PerformanceLab"},
        )
        state = (
            "READY"
            if any(route.ready for route in routes)
            else "MATERIALIZED"
            if materialized_list
            else "REGISTERED"
            if registered_list
            else None
        )
        actions = sorted(
            {item.preparation_action for item in source_items if item.preparation_action}
        )
        if not actions and registered_list and not materialized_list:
            actions = ["materialize"]
        rights, noncommercial_only, local_only = _rights([dataset.dataset_id], dataset_by_id)
        resources.append(
            CatalogResourceView(
                resource_kind="performance_session",
                resource_id=f"{dataset.dataset_id}/{detail.session.session_id}",
                label=detail.session.label or detail.session.session_id,
                dataset_ids=[dataset.dataset_id],
                providers=[dataset.provider],
                external_ids=[detail.session.session_id],
                session_id=detail.session.session_id,
                rights_identifiers=rights,
                noncommercial_only=noncommercial_only,
                local_only=local_only,
                availability_state=state,
                stages=_stages(
                    upstream=upstream_list,
                    registered=registered_list,
                    materialized=materialized_list,
                    routes=routes,
                    state=state,
                    source_known=bool(dataset.upstream_urls),
                ),
                upstream_capabilities=upstream_list,
                registered_capabilities=registered_list,
                materialized_capabilities=materialized_list,
                materialized_grains=grain_list,
                routes=routes,
                preparation_eligible=bool(actions),
                preparation_actions=actions,
            )
        )

    resources.sort(
        key=lambda item: (
            item.sport_name
            or (
                "Human performance"
                if item.resource_kind in {"performance_dataset", "performance_session"}
                else "Other"
            ),
            item.competition_name or "",
            item.edition_label or "",
            item.label.casefold(),
            item.resource_id,
        )
    )
    return CatalogReadModelView(resources=resources)
