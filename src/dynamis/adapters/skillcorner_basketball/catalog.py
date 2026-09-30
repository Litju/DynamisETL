"""Metadata-first registration of the pinned ACB sample corpus."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from dynamis.adapters.skillcorner_basketball import authorities
from dynamis.config import ConfigurationError, repository_root, settings
from dynamis.contracts import (
    ParticipantRole,
    Session,
    SessionKind,
    SessionParticipant,
    Subject,
)
from dynamis.contracts.sports import (
    Capability,
    Competition,
    CompetitionEdition,
    Contest,
    ContestSide,
    ContestTeam,
    EditionKind,
    ProviderIdentityCrosswalk,
    SessionSportContext,
    SourceCatalogEntry,
    SourceCatalogState,
    SourceObjectKind,
    Sport,
    SportsContext,
    SportsEntityKind,
    Team,
    TeamRosterMembership,
    canonical_sports_id,
    provider_crosswalk,
)
from dynamis.pipeline.streams import ProviderDomain, SourceAuthorities
from dynamis.registry import source_by_id, validate_registry

DATASET_ID = authorities.DATASET_ID
CORPUS_PATH = repository_root() / "sources" / "skillcorner-basketball-corpus.json"
_HTTP_URL = TypeAdapter(HttpUrl)


def load_corpus_manifest(path: Path | None = None) -> dict[str, Any]:
    corpus = json.loads((path or CORPUS_PATH).read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 1:
        raise ValueError("unsupported SkillCorner basketball corpus manifest")
    if len(corpus.get("matches", [])) != 10:
        raise ValueError("the SkillCorner basketball sample manifest must contain 10 games")
    if len({str(item["match"]["id"]) for item in corpus["matches"]}) != 10:
        raise ValueError("SkillCorner basketball match ids must be unique")
    coverage = corpus.get("coverage", {})
    sample_teams = {
        str(item[team][key]["id"])
        for item in corpus["matches"]
        for team, key in (("match", "home_team"), ("match", "away_team"))
    }
    manifest_teams = {str(team["provider_team_id"]) for team in corpus.get("teams", [])}
    expected_coverage = {
        "sample_game_count": len(corpus["matches"]),
        "sample_game_team_count": len(sample_teams),
        "season_aggregate_game_count": 293,
        "season_aggregate_team_count": 18,
        "season_schedule_game_count": 327,
    }
    if (
        manifest_teams != sample_teams
        or any(coverage.get(key) != value for key, value in expected_coverage.items())
        or coverage.get("aggregate_scope") != "offense_only"
    ):
        raise ValueError("SkillCorner basketball coverage facts do not match the pinned corpus")
    keys = [str(item["key"]) for item in corpus.get("files", [])]
    if len(keys) != len(set(keys)):
        raise ValueError("SkillCorner basketball upstream file keys must be unique")
    return corpus


def contest_id(game_id: str) -> str:
    return canonical_sports_id(authorities.NAMESPACE, SportsEntityKind.CONTEST, game_id)


def edition_id(corpus: dict[str, Any] | None = None) -> str:
    manifest = corpus or load_corpus_manifest()
    return canonical_sports_id(
        authorities.NAMESPACE,
        SportsEntityKind.EDITION,
        str(manifest["upstream"]["competition_edition"]["provider_id"]),
    )


def contest_catalog_id(game_id: str) -> str:
    digest = hashlib.md5(
        f"{DATASET_ID}:contest:{game_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return f"src-{digest}"


def aggregate_catalog_id(edition: str, family: str) -> str:
    digest = hashlib.md5(
        f"{DATASET_ID}:aggregate:{edition}:{family}".encode(), usedforsecurity=False
    ).hexdigest()
    return f"src-{digest}"


def _name(player: dict[str, Any]) -> str:
    return " ".join(
        str(value).strip()
        for value in (player.get("firstName"), player.get("lastName"))
        if value is not None and str(value).strip()
    )


def build_game_domain(corpus: dict[str, Any], item: dict[str, Any]) -> ProviderDomain:
    """Create one metadata-only game domain; no source file is opened here."""
    upstream = corpus["upstream"]
    match = item["match"]
    detail = item["detail"]
    game_id = str(match["id"])
    start = datetime.fromisoformat(str(match["date_time"]).replace("Z", "+00:00"))
    competition_provider_id = str(upstream["competition"]["provider_id"])
    edition_provider_id = str(upstream["competition_edition"]["provider_id"])
    competition = Competition(
        competition_id=canonical_sports_id(
            authorities.NAMESPACE, SportsEntityKind.COMPETITION, competition_provider_id
        ),
        sport_id="basketball",
        name=str(upstream["competition"]["name"]),
    )
    edition = CompetitionEdition(
        edition_id=canonical_sports_id(
            authorities.NAMESPACE, SportsEntityKind.EDITION, edition_provider_id
        ),
        competition_id=competition.competition_id,
        label=str(upstream["season"]["label"]),
        kind=EditionKind.LEAGUE_SEASON,
    )
    team_ids: dict[str, str] = {}
    aliases = {
        str(alias["player_id"]): str(alias["canonical_player_id"])
        for alias in corpus.get("player_aliases", [])
    }
    alias_names = {
        str(alias["canonical_player_id"]): str(alias["canonical_player_name"])
        for alias in corpus.get("player_aliases", [])
    }
    teams: list[Team] = []
    participants: list[SessionParticipant] = []
    subjects: dict[str, Subject] = {}
    roster_memberships: list[TeamRosterMembership] = []
    crosswalks: list[ProviderIdentityCrosswalk] = [
        provider_crosswalk(
            provider_namespace=authorities.NAMESPACE,
            entity_kind=SportsEntityKind.COMPETITION,
            provider_entity_id=competition_provider_id,
            source_authority=f"matches.json@{upstream['revision']}",
            metadata={"name": competition.name},
        ),
        provider_crosswalk(
            provider_namespace=authorities.NAMESPACE,
            entity_kind=SportsEntityKind.EDITION,
            provider_entity_id=edition_provider_id,
            source_authority=f"matches.json@{upstream['revision']}",
            metadata={"label": edition.label},
        ),
    ]

    sides = (
        ("home", match["home_team"], detail["homeTeam"], ContestSide.HOME, match["home_score"]),
        ("away", match["away_team"], detail["awayTeam"], ContestSide.AWAY, match["away_score"]),
    )
    contest_teams: list[ContestTeam] = []
    for side_order, (_key, match_team, detail_team, side, score) in enumerate(sides):
        provider_team_id = str(match_team["id"])
        team_id = canonical_sports_id(
            authorities.NAMESPACE, SportsEntityKind.TEAM, provider_team_id
        )
        team_ids[provider_team_id] = team_id
        teams.append(
            Team(team_id=team_id, sport_id="basketball", display_name=str(match_team["name"]))
        )
        contest_teams.append(
            ContestTeam(
                contest_id=contest_id(game_id),
                team_id=team_id,
                side=side,
                side_order=side_order,
                score=int(score),
            )
        )
        crosswalks.append(
            provider_crosswalk(
                provider_namespace=authorities.NAMESPACE,
                entity_kind=SportsEntityKind.TEAM,
                provider_entity_id=provider_team_id,
                source_authority=f"game_data.json@{upstream['revision']}",
                metadata={"display_name": str(match_team["name"])},
            )
        )
        for player in detail_team.get("players", []):
            provider_player_id = str(player["playerId"])
            canonical_player_id = aliases.get(provider_player_id, provider_player_id)
            subjects.setdefault(
                provider_player_id,
                Subject(dataset_id=DATASET_ID, subject_id=provider_player_id),
            )
            participants.append(
                SessionParticipant(
                    dataset_id=DATASET_ID,
                    session_id=game_id,
                    subject_id=provider_player_id,
                    role=ParticipantRole.PLAYER,
                    group_label=str(match_team["name"]),
                )
            )
            roster_memberships.append(
                TeamRosterMembership(
                    dataset_id=DATASET_ID,
                    subject_id=provider_player_id,
                    team_id=team_id,
                    competition_edition_id=edition.edition_id,
                )
            )
            player_crosswalk = provider_crosswalk(
                provider_namespace=authorities.NAMESPACE,
                entity_kind=SportsEntityKind.SUBJECT,
                provider_entity_id=provider_player_id,
                source_authority=f"game_data.json@{upstream['revision']}",
                metadata={
                    "display_name": alias_names.get(canonical_player_id, _name(player)),
                    "jersey": str(player["jersey"]),
                    "canonical_provider_player_id": canonical_player_id,
                },
            ).model_copy(
                update={
                    "canonical_entity_id": canonical_sports_id(
                        authorities.NAMESPACE,
                        SportsEntityKind.SUBJECT,
                        canonical_player_id,
                    )
                }
            )
            crosswalks.append(player_crosswalk)

    metadata = {
        "provider_game_id": game_id,
        "competition_name": str(match["competition_name"]),
        "season": str(match["season"]),
        "status": str(match["status"]),
        "completed": str(match["status"]).lower() in {"closed", "complete", "completed"},
        "home_score": int(match["home_score"]),
        "away_score": int(match["away_score"]),
        "play_by_play_available": False,
        "tracking_available": True,
        "period_count": 0,
    }
    contest = Contest(
        contest_id=contest_id(game_id),
        sport_id="basketball",
        competition_edition_id=edition.edition_id,
        scheduled_start_at=start,
        actual_start_at=None,
        home_away_supported=True,
        source_authority=f"matches.json and game_data.json@{upstream['revision']}",
    )
    crosswalks.append(
        provider_crosswalk(
            provider_namespace=authorities.NAMESPACE,
            entity_kind=SportsEntityKind.CONTEST,
            provider_entity_id=game_id,
            source_authority=f"matches.json@{upstream['revision']}",
            metadata=metadata,
        )
    )
    sport = Sport(sport_id="basketball", code="basketball", display_name="Basketball")
    session = Session(
        dataset_id=DATASET_ID,
        session_id=game_id,
        kind=SessionKind.MATCH,
        label=f"{match['home_team']['name']} vs {match['away_team']['name']}",
        started_at=start,
    )
    context = SportsContext(
        sport=sport,
        competition=competition,
        edition=edition,
        teams=tuple(teams),
        contest=contest,
        contest_teams=tuple(contest_teams),
        roster_memberships=tuple(roster_memberships),
        session=SessionSportContext(
            dataset_id=DATASET_ID,
            session_id=game_id,
            contest_id=contest.contest_id,
            source_catalog_entry_id=contest_catalog_id(game_id),
        ),
        crosswalks=tuple(crosswalks),
    )
    return ProviderDomain(
        session=session,
        subjects=tuple(subjects.values()),
        participants=tuple(participants),
        trials=(),
        streams=(),
        authorities=SourceAuthorities(),
        session_metadata={
            "match_id": game_id,
            "metadata_only": True,
            "scheduled_start_at": start.isoformat(),
            "home_team": {"team_id": team_ids[str(match["home_team"]["id"])], **match["home_team"]},
            "away_team": {"team_id": team_ids[str(match["away_team"]["id"])], **match["away_team"]},
        },
        sports_contexts=(context,),
    )


def _preserve_materialized_contest_metadata(
    domain: ProviderDomain,
    existing_metadata: dict[str, Any] | None,
) -> ProviderDomain:
    if not existing_metadata:
        return domain
    contexts = []
    for context in domain.sports_contexts:
        crosswalks = []
        for crosswalk in context.crosswalks:
            if crosswalk.entity_kind is not SportsEntityKind.CONTEST:
                crosswalks.append(crosswalk)
                continue
            metadata = dict(crosswalk.metadata)
            for key in ("play_by_play_available", "tracking_available"):
                if existing_metadata.get(key) is True:
                    metadata[key] = True
            previous_period_count = existing_metadata.get("period_count")
            if (
                isinstance(previous_period_count, int)
                and not isinstance(previous_period_count, bool)
                and previous_period_count > int(metadata.get("period_count", 0))
            ):
                metadata["period_count"] = previous_period_count
            crosswalks.append(crosswalk.model_copy(update={"metadata": metadata}))
        contexts.append(context.model_copy(update={"crosswalks": tuple(crosswalks)}))
    return replace(domain, sports_contexts=tuple(contexts))


def _defer_contest_catalog_link(domain: ProviderDomain) -> ProviderDomain:
    """Persist session metadata before linking the contest catalog row."""
    contexts = tuple(
        context.model_copy(
            update={"session": context.session.model_copy(update={"source_catalog_entry_id": None})}
        )
        for context in domain.sports_contexts
    )
    return replace(domain, sports_contexts=contexts)


def build_catalog_entries(source, corpus: dict[str, Any]) -> list[dict[str, Any]]:
    upstream = corpus["upstream"]
    revision = upstream["revision"]
    file_by_key = {str(item["key"]): item for item in corpus["files"]}
    competition_id = canonical_sports_id(
        authorities.NAMESPACE,
        SportsEntityKind.COMPETITION,
        str(upstream["competition"]["provider_id"]),
    )
    season_edition_id = edition_id(corpus)
    teams_by_provider_id = {
        str(item["provider_team_id"]): canonical_sports_id(
            authorities.NAMESPACE, SportsEntityKind.TEAM, str(item["provider_team_id"])
        )
        for item in corpus["teams"]
    }
    coverage = corpus["coverage"]

    def file_family_asset(key: str) -> dict[str, Any]:
        asset = file_by_key[key]
        return {
            "key": key,
            "size_bytes": int(asset["size_bytes"]),
            "sha1": asset.get("sha1"),
            "sha256": asset.get("sha256"),
            "upstream_provider": "github",
            "upstream_revision": revision,
        }

    rights = source.license.model_dump(mode="json")
    entries: list[SourceCatalogEntry] = []
    for item in corpus["matches"]:
        match = item["match"]
        game_id = str(match["id"])
        key = f"data/matches/{game_id}/{game_id}_game_data.json"
        asset = file_by_key[key]
        event_key = f"data/matches/{game_id}/{game_id}_dynamic_events.json"
        tracking_key = f"data/matches/{game_id}/{game_id}_tracking_data.jsonl.gz"
        provider_metadata = {
            "provider_game_id": game_id,
            "scheduled_start_at": match["date_time"],
            "season": match["season"],
            "status": match["status"],
            "score": [int(match["home_score"]), int(match["away_score"])],
            "roster_size": len(item["detail"]["homeTeam"]["players"])
            + len(item["detail"]["awayTeam"]["players"]),
            "file_families": {
                "game_data": file_family_asset(key),
                "dynamic_events": file_family_asset(event_key),
                "tracking": file_family_asset(tracking_key),
            },
            "dense_materialized": False,
        }
        entries.append(
            SourceCatalogEntry(
                entry_id=contest_catalog_id(game_id),
                provider=source.provider,
                dataset=source.dataset_id,
                external_id=f"contest:{game_id}",
                object_kind=SourceObjectKind.CONTEST,
                registry_dataset_id=DATASET_ID,
                registry_version=revision,
                registry_file_key=key,
                sport_id="basketball",
                competition_id=competition_id,
                competition_edition_id=season_edition_id,
                teams=(
                    teams_by_provider_id[str(match["home_team"]["id"])],
                    teams_by_provider_id[str(match["away_team"]["id"])],
                ),
                upstream_url=_HTTP_URL.validate_python(
                    f"https://raw.githubusercontent.com/{upstream['repository']}/{revision}/{key}"
                ),
                upstream_revision=revision,
                asset_identity=str(asset["sha1"]),
                expected_size_bytes=int(asset["size_bytes"]),
                rights=rights,
                provider_metadata=provider_metadata,
                upstream_capabilities=(
                    Capability.TRACKING.value,
                    Capability.BALL_TRACKING.value,
                    Capability.EVENTS.value,
                ),
                discovered_at=datetime.now(UTC),
                availability_state=SourceCatalogState.REGISTERED,
            )
        )
    sample_team_count = len(set(teams_by_provider_id.values()))
    for aggregate in corpus["aggregates"]:
        asset = aggregate["asset"]
        family = str(aggregate["family"])
        key = str(asset["key"])
        entries.append(
            SourceCatalogEntry(
                entry_id=aggregate_catalog_id(season_edition_id, family),
                provider=source.provider,
                dataset=source.dataset_id,
                external_id=f"aggregate:{season_edition_id}:{family}",
                object_kind=SourceObjectKind.AGGREGATE,
                registry_dataset_id=DATASET_ID,
                registry_version=revision,
                registry_file_key=key,
                sport_id="basketball",
                competition_id=competition_id,
                competition_edition_id=season_edition_id,
                teams=(),
                upstream_url=_HTTP_URL.validate_python(
                    f"https://raw.githubusercontent.com/{upstream['repository']}/{revision}/{key}"
                ),
                upstream_revision=revision,
                asset_identity=str(asset["sha1"]),
                expected_size_bytes=int(asset["size_bytes"]),
                rights=rights,
                provider_metadata={
                    "aggregate_family": family,
                    "source_file_key": key,
                    "provider_id_columns": ["player_id", "team_id", "season_id"],
                    "season": str(upstream["season"]["label"]),
                    "population_scope": coverage["aggregate_scope"],
                    "sample_game_team_count": sample_team_count,
                    "season_aggregate_game_count": coverage["season_aggregate_game_count"],
                    "season_aggregate_team_count": coverage["season_aggregate_team_count"],
                    "season_schedule_game_count": coverage["season_schedule_game_count"],
                },
                upstream_capabilities=(Capability.SEASON_AGGREGATE.value,),
                discovered_at=datetime.now(UTC),
                availability_state=SourceCatalogState.REGISTERED,
            )
        )
    return [
        {
            **entry.model_dump(mode="python"),
            "upstream_url": str(entry.upstream_url),
            "object_kind": entry.object_kind.value,
            "availability_state": SourceCatalogState.REGISTERED.value,
            "teams": list(entry.teams),
            "upstream_capabilities": list(entry.upstream_capabilities),
        }
        for entry in entries
    ]


def _git_blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def validate_upstream_corpus(*, corpus: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate pinned metadata and LFS pointers without reading dense objects."""
    from dynamis.acquisition.plan import plan_acquisition

    manifest = corpus or load_corpus_manifest()
    registry = validate_registry()
    source = source_by_id(registry, DATASET_ID)
    revision = str(manifest["upstream"]["revision"])
    expected = {str(item["key"]): item for item in manifest["files"]}
    planned_bytes = 0
    with requests.Session() as http:
        plan = plan_acquisition(
            DATASET_ID,
            version=revision,
            all_files=True,
            registry=registry,
            session=http,
        )
        for item in plan.files:
            pinned = expected[item.key]
            if item.size_bytes != int(pinned["size_bytes"]):
                raise ValueError(f"{item.key}: upstream size differs from the corpus manifest")
            if item.git_blob_sha1 is not None and item.git_blob_sha1 != pinned["sha1"]:
                raise ValueError(
                    f"{item.key}: upstream Git object differs from the corpus manifest"
                )
            if pinned["sha256"] != "unknown" and item.upstream_sha256 != pinned["sha256"]:
                raise ValueError(
                    f"{item.key}: upstream LFS digest differs from the corpus manifest"
                )
            planned_bytes += item.size_bytes

        base = f"https://raw.githubusercontent.com/{manifest['upstream']['repository']}/{revision}"
        index_key = str(manifest["upstream"]["match_index_key"])
        response = http.get(f"{base}/{index_key}", timeout=(15.0, 60.0))
        response.raise_for_status()
        index_raw = response.content
        if _git_blob_sha1(index_raw) != manifest["upstream"]["match_index_git_blob_sha1"]:
            raise ValueError("pinned matches.json identity changed")
        remote_matches = json.loads(index_raw)
        pinned_matches = [item["match"] for item in manifest["matches"]]
        if remote_matches != pinned_matches:
            raise ValueError("pinned matches.json metadata differs from the committed corpus")
        metadata_bytes = len(index_raw)
        for item in manifest["matches"]:
            match_id = str(item["match"]["id"])
            key = f"data/matches/{match_id}/{match_id}_game_data.json"
            response = http.get(f"{base}/{key}", timeout=(15.0, 60.0))
            response.raise_for_status()
            raw = response.content
            if _git_blob_sha1(raw) != expected[key]["sha1"]:
                raise ValueError(f"{key}: pinned roster metadata identity changed")
            if json.loads(raw) != item["detail"]:
                raise ValueError(f"{key}: pinned roster metadata differs from the corpus")
            metadata_bytes += len(raw)
        aliases_key = "data/player_id_aliases.csv"
        response = http.get(f"{base}/{aliases_key}", timeout=(15.0, 60.0))
        response.raise_for_status()
        aliases_raw = response.content
        if _git_blob_sha1(aliases_raw) != expected[aliases_key]["sha1"]:
            raise ValueError("pinned player_id_aliases.csv identity changed")
        aliases = list(csv.DictReader(io.StringIO(aliases_raw.decode("utf-8-sig"))))
        pinned_aliases = [
            {key: str(value) for key, value in item.items()}
            for item in manifest.get("player_aliases", [])
        ]
        if aliases != pinned_aliases:
            raise ValueError("pinned player aliases differ from the committed corpus")
        metadata_bytes += len(aliases_raw)
    if source.version(revision).version != revision:
        raise ValueError("basketball corpus version is not registered")
    return {
        "revision": revision,
        "matches": len(manifest["matches"]),
        "upstream_files_resolved": len(expected),
        "planned_bytes": planned_bytes,
        "metadata_bytes_read": metadata_bytes,
        "dense_bytes_downloaded": 0,
    }


def register_corpus(*, verify_upstream: bool = True) -> dict[str, Any]:
    corpus = load_corpus_manifest()
    registry = validate_registry()
    source = source_by_id(registry, DATASET_ID)
    revision = str(corpus["upstream"]["revision"])
    source.version(revision)
    validation = validate_upstream_corpus(corpus=corpus) if verify_upstream else None
    from dynamis.pipeline.persist import persist_source
    from dynamis.storage.control_plane import control_plane_engine

    config = settings()
    engine = control_plane_engine(config)
    written: dict[str, int] = {}
    try:
        with engine.begin() as connection:
            written.update(persist_source(connection, source))
            for key, count in persist_catalog(connection, source, corpus).items():
                written[key] = written.get(key, 0) + count
    finally:
        engine.dispose()
    return {
        "dataset_id": DATASET_ID,
        "revision": revision,
        "matches": len(corpus["matches"]),
        "teams": len(corpus["teams"]),
        "contest_entries": len(corpus["matches"]),
        "season_aggregate_entries": len(corpus["aggregates"]),
        "upstream_validation": validation,
        "dense_bytes_downloaded": 0,
        "rows_written": written,
    }


def persist_catalog(connection, source, corpus: dict[str, Any]) -> dict[str, int]:
    from dynamis.pipeline.persist import (
        CLOCK_MAPPING_TABLE,
        PROVIDER_CROSSWALK_TABLE,
        SESSION_SPORT_CONTEXT_TABLE,
        SOURCE_CATALOG_TABLE,
        SPATIAL_REFERENCE_TABLE,
        SURFACE_GEOMETRY_TABLE,
        _upsert_refresh,
        persist_domain,
    )

    written: dict[str, int] = {}
    for item in corpus["matches"]:
        game_id = str(item["match"]["id"])
        existing_metadata = connection.execute(
            select(PROVIDER_CROSSWALK_TABLE.c.metadata_json).where(
                PROVIDER_CROSSWALK_TABLE.c.provider_namespace == authorities.NAMESPACE,
                PROVIDER_CROSSWALK_TABLE.c.entity_kind == SportsEntityKind.CONTEST.value,
                PROVIDER_CROSSWALK_TABLE.c.provider_entity_id == game_id,
            )
        ).scalar_one_or_none()
        domain = _preserve_materialized_contest_metadata(
            build_game_domain(corpus, item), existing_metadata
        )
        rows = persist_domain(connection, _defer_contest_catalog_link(domain))
        for key, count in rows.items():
            written[key] = written.get(key, 0) + count
    entries = build_catalog_entries(source, corpus)
    statement = pg_insert(SOURCE_CATALOG_TABLE).values(entries)
    statement = statement.on_conflict_do_update(
        index_elements=["entry_id"],
        set_={
            name: statement.excluded[name]
            for name in (
                "provider",
                "dataset",
                "registry_dataset_id",
                "registry_version",
                "registry_file_key",
                "external_id",
                "object_kind",
                "sport_id",
                "competition_id",
                "competition_edition_id",
                "teams",
                "upstream_url",
                "upstream_revision",
                "asset_identity",
                "expected_size_bytes",
                "rights",
                "provider_metadata",
                "upstream_capabilities",
            )
        },
    )
    connection.execute(statement)
    written["basketball_source_catalog_entry"] = len(entries)
    for item in corpus["matches"]:
        game_id = str(item["match"]["id"])
        connection.execute(
            SESSION_SPORT_CONTEXT_TABLE.update()
            .where(
                SESSION_SPORT_CONTEXT_TABLE.c.dataset_id == DATASET_ID,
                SESSION_SPORT_CONTEXT_TABLE.c.session_id == game_id,
            )
            .values(source_catalog_entry_id=contest_catalog_id(game_id))
        )
    spatial = authorities.spatial_reference().model_dump(mode="json")
    surface = authorities.surface_geometry().model_dump(mode="json")
    mappings = [item.model_dump(mode="json") for item in authorities.clock_mappings()]
    written["spatial_reference"] = _upsert_refresh(connection, SPATIAL_REFERENCE_TABLE, [spatial])
    written["surface_geometry"] = _upsert_refresh(connection, SURFACE_GEOMETRY_TABLE, [surface])
    written["clock_mapping"] = _upsert_refresh(connection, CLOCK_MAPPING_TABLE, mappings)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dynamis-register-skillcorner-basketball",
        description=(
            "Register the 10-game ACB catalog without acquiring tracking or event payloads."
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--skip-upstream-validation", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = register_corpus(verify_upstream=not args.skip_upstream_validation)
    except (ConfigurationError, OSError, ValueError, requests.RequestException) as exc:
        print(f"dynamis-register-skillcorner-basketball: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"registered {result['matches']} ACB games; "
            f"{result['dense_bytes_downloaded']} dense bytes downloaded"
        )
    return 0


__all__ = [
    "DATASET_ID",
    "aggregate_catalog_id",
    "build_catalog_entries",
    "build_game_domain",
    "contest_catalog_id",
    "contest_id",
    "edition_id",
    "load_corpus_manifest",
    "main",
    "persist_catalog",
    "register_corpus",
    "validate_upstream_corpus",
]
