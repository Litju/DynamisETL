"""Pinned SkillCorner corpus metadata and metadata-only registration."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from pydantic import HttpUrl, TypeAdapter

from dynamis.acquisition.plan import plan_acquisition
from dynamis.config import ConfigurationError, repository_root, settings
from dynamis.contracts import DatasetSource
from dynamis.contracts.sports import (
    ContestSide,
    EditionKind,
    PeriodKind,
    SourceCatalogEntry,
    SourceCatalogState,
    SourceObjectKind,
    SportsEntityKind,
    canonical_sports_id,
    provider_crosswalk,
    provider_crosswalk_id,
)
from dynamis.registry import RegistryError, source_by_id, validate_registry
from dynamis.storage.control_plane import control_plane_engine

DATASET_ID = "skillcorner-opendata"
NAMESPACE = "skillcorner_opendata"
_HTTP_URL = TypeAdapter(HttpUrl)
FAMILIES = {
    "match_metadata": "_match.json",
    "tracking": "_tracking_extrapolated.jsonl",
    "dynamic_events": "_dynamic_events.csv",
    "phases": "_phases_of_play.csv",
}


def load_corpus_manifest(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the committed metadata snapshot for the pinned release."""
    manifest_path = path or repository_root() / "sources" / "skillcorner-corpus.json"
    try:
        corpus = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load SkillCorner corpus manifest {manifest_path}: {exc}") from exc
    if corpus.get("schema_version") != 1 or corpus.get("dataset_id") != DATASET_ID:
        raise ValueError("unsupported SkillCorner corpus manifest")
    revision = corpus.get("upstream", {}).get("revision")
    if not isinstance(revision, str) or len(revision) != 40:
        raise ValueError("SkillCorner corpus manifest must pin a 40-character Git revision")
    matches = corpus.get("matches")
    if not isinstance(matches, list) or len(matches) != 20:
        raise ValueError("pinned SkillCorner A-League corpus must contain 20 matches")
    match_ids = [str(match.get("id")) for match in matches]
    if len(match_ids) != len(set(match_ids)):
        raise ValueError("pinned SkillCorner corpus contains duplicate match IDs")
    teams = corpus.get("teams")
    if not isinstance(teams, list) or len(teams) != 13:
        raise ValueError("pinned SkillCorner A-League corpus must contain 13 teams")
    expected_ids = {"61", "95", "870"}
    for match in matches:
        if {
            str(match.get("competition_id")),
            str(match.get("season_id")),
            str(match.get("competition_edition_id")),
        } != expected_ids:
            raise ValueError(f"match {match.get('id')} is outside the pinned A-League edition")
        families = match.get("families", {})
        if set(families) != set(FAMILIES):
            raise ValueError(f"match {match.get('id')} has an incomplete file-family inventory")
        for family, suffix in FAMILIES.items():
            key = families[family].get("key", "")
            if not key.endswith(f"/{match['id']}{suffix}"):
                raise ValueError(f"match {match['id']} has an invalid {family} key")
    files = corpus.get("files")
    keys = [item.get("key") for item in files] if isinstance(files, list) else []
    if len(keys) != 86 or len(keys) != len(set(keys)):
        raise ValueError("SkillCorner corpus manifest must inventory 86 unique upstream assets")
    pose_files = corpus.get("pose", {}).get("files")
    pose_ids = {str(item.get("match_id")) for item in pose_files or []}
    if pose_ids != set(corpus.get("pose", {}).get("match_ids", [])):
        raise ValueError("SkillCorner pose inventory does not match the declared pose match IDs")
    if any(item.get("upstream_provider") != "huggingface" for item in pose_files or []):
        raise ValueError("SkillCorner pose assets must use the pinned Hugging Face source")
    return corpus


def _match_signature(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(record["id"]),
        "date_time": record["date_time"],
        "home_team": {
            "id": int(record["home_team"]["id"]),
            "short_name": record["home_team"]["short_name"],
        },
        "away_team": {
            "id": int(record["away_team"]["id"]),
            "short_name": record["away_team"]["short_name"],
        },
        "status": record["status"],
        "competition_id": int(record["competition_id"]),
        "season_id": int(record["season_id"]),
        "competition_edition_id": int(record["competition_edition_id"]),
    }


def validate_upstream_corpus(
    *,
    corpus: dict[str, Any] | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Verify pinned index bytes and every declared family identity, without fetching assets."""
    manifest = corpus or load_corpus_manifest()
    registry = validate_registry()
    source = source_by_id(registry, DATASET_ID)
    revision = manifest["upstream"]["revision"]
    version = source.version(revision)
    manifest_keys = {item["key"] for item in manifest["files"]}
    manifest_files = {item["key"]: item for item in manifest["files"]}
    registry_files = {item.key: item for item in version.retrieval.files}
    if set(registry_files) != manifest_keys:
        raise ValueError("SkillCorner registry keys do not match the pinned corpus manifest")
    close_session = session is None
    http = session or requests.Session()
    try:
        plan = plan_acquisition(
            DATASET_ID,
            version=revision,
            all_files=True,
            registry=registry,
            session=http,
        )
        plan_files = {item.key: item for item in plan.files}
        if set(plan_files) != manifest_keys:
            raise ValueError(
                "upstream resolver returned an incomplete SkillCorner family inventory"
            )
        for key, resolved in plan_files.items():
            expected = manifest_files[key]
            declared = registry_files[key]
            if resolved.size_bytes != expected["size_bytes"]:
                raise ValueError(f"{key}: resolved size disagrees with the pinned corpus manifest")
            if expected.get("sha256") not in (None, "unknown", resolved.upstream_sha256):
                raise ValueError(
                    f"{key}: resolved SHA-256 disagrees with the pinned corpus manifest"
                )
            expected_sha1 = expected.get("sha1")
            if expected_sha1 not in (None, "unknown"):
                resolved_sha1 = resolved.git_blob_sha1 or resolved.upstream_sha1
                if resolved_sha1 is None or expected_sha1.lower() != resolved_sha1.lower():
                    raise ValueError(
                        f"{key}: resolved SHA-1 disagrees with the pinned corpus manifest"
                    )
            if declared.size_bytes != expected["size_bytes"]:
                raise ValueError(f"{key}: registry size disagrees with the pinned corpus manifest")
            if declared.sha1 not in ("unknown", expected_sha1):
                raise ValueError(f"{key}: registry SHA-1 disagrees with the pinned corpus manifest")
        index_url = (
            f"https://raw.githubusercontent.com/{manifest['upstream']['repository']}/"
            f"{revision}/{manifest['upstream']['match_index_key']}"
        )
        response = http.get(index_url, timeout=(15.0, 60.0))
        try:
            if not response.ok:
                raise ValueError(
                    f"pinned SkillCorner match index returned HTTP {response.status_code}"
                )
            raw = response.content
        finally:
            response.close()
        blob_sha1 = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
        if blob_sha1 != manifest["upstream"]["match_index_git_blob_sha1"]:
            raise ValueError("pinned SkillCorner matches.json blob identity changed")
        upstream_matches = json.loads(raw)
        if [_match_signature(item) for item in upstream_matches] != [
            _match_signature(item) for item in manifest["matches"]
        ]:
            raise ValueError("committed SkillCorner corpus does not match pinned matches.json")
        return {
            "revision": revision,
            "index_blob_sha1": blob_sha1,
            "match_count": len(upstream_matches),
            "file_count": len(plan.files),
            "planned_bytes": plan.total_bytes,
            "downloaded_bytes": 0,
        }
    finally:
        if close_session:
            http.close()


def _stable_catalog_id(external_id: str) -> str:
    return (
        "src-"
        + hashlib.md5(f"{DATASET_ID}:{external_id}".encode(), usedforsecurity=False).hexdigest()
    )


def skillcorner_contest_catalog_id(match_id: str) -> str:
    return _stable_catalog_id(f"contest:{match_id}")


def skillcorner_aggregate_catalog_id(edition_id: str, family: str) -> str:
    return _stable_catalog_id(f"aggregate:{edition_id}:{family}")


def _canonical_team(provider_team_id: object) -> str:
    return canonical_sports_id(NAMESPACE, SportsEntityKind.TEAM, str(provider_team_id))


def _provider_crosswalk_row(
    kind: SportsEntityKind,
    provider_id: object,
    *,
    source_authority: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    crosswalk = provider_crosswalk(
        provider_namespace=NAMESPACE,
        entity_kind=kind,
        provider_entity_id=str(provider_id),
        source_authority=source_authority,
        metadata=metadata,
    )
    row = crosswalk.model_dump(mode="python")
    row["entity_kind"] = crosswalk.entity_kind.value
    row["crosswalk_id"] = provider_crosswalk_id(crosswalk)
    row["metadata_json"] = row.pop("metadata")
    return row


def build_catalog_entries(
    source: DatasetSource,
    corpus: dict[str, Any],
    *,
    discovered_at: datetime | None = None,
) -> list[dict[str, Any]]:
    upstream = corpus["upstream"]
    revision = upstream["revision"]
    discovered = discovered_at or datetime.now(UTC)
    rights = source.license.model_dump(mode="json")
    competition_id = canonical_sports_id(
        NAMESPACE, SportsEntityKind.COMPETITION, upstream["competition"]["provider_id"]
    )
    edition_id = canonical_sports_id(
        NAMESPACE, SportsEntityKind.EDITION, upstream["competition_edition"]["provider_id"]
    )
    team_ids = {
        str(item["provider_team_id"]): _canonical_team(item["provider_team_id"])
        for item in corpus["teams"]
    }
    pose_by_match = {str(item["match_id"]): item for item in corpus["pose"]["files"]}
    entries: list[SourceCatalogEntry] = []
    family_capabilities = {
        "tracking": ("TRACKING", "BALL_TRACKING"),
        "dynamic_events": ("EVENTS",),
        "phases": ("PHASES",),
    }
    for match in corpus["matches"]:
        match_id = str(match["id"])
        detail = match["detail"]
        pose = pose_by_match.get(match_id)
        file_inventory = {
            family: {
                "key": asset["key"],
                "size_bytes": asset["size_bytes"],
                "sha1": asset["sha1"],
                "sha256": asset["sha256"],
                "upstream_provider": "github",
                "upstream_revision": revision,
            }
            for family, asset in match["families"].items()
        }
        if pose:
            file_inventory["pose"] = {
                "key": pose["key"],
                "size_bytes": pose["size_bytes"],
                "sha256": pose["sha256"],
                "upstream_provider": "huggingface",
                "upstream_revision": corpus["pose"]["revision"],
            }
        capabilities = [value for family in family_capabilities.values() for value in family]
        if pose:
            capabilities.append("POSE")
        metadata = {
            "matches_json_status": match["status"],
            "match_json_status": detail.get("status"),
            "date_time": match["date_time"],
            "provider_team_ids": [str(match["home_team"]["id"]), str(match["away_team"]["id"])],
            "home_team_score": detail.get("home_team_score"),
            "away_team_score": detail.get("away_team_score"),
            "competition_id": match["competition_id"],
            "season_id": match["season_id"],
            "competition_edition_id": match["competition_edition_id"],
            "file_families": file_inventory,
            "pose_availability": "UPSTREAM_AVAILABLE" if pose else "UPSTREAM_UNAVAILABLE",
        }
        match_asset = match["families"]["match_metadata"]
        contest = SourceCatalogEntry(
            entry_id=skillcorner_contest_catalog_id(match_id),
            provider=source.provider,
            dataset=source.dataset_id,
            external_id=f"contest:{match_id}",
            object_kind=SourceObjectKind.CONTEST,
            registry_dataset_id=DATASET_ID,
            registry_version=revision,
            registry_file_key=match_asset["key"],
            sport_id="football",
            competition_id=competition_id,
            competition_edition_id=edition_id,
            teams=(
                team_ids[str(match["home_team"]["id"])],
                team_ids[str(match["away_team"]["id"])],
            ),
            upstream_url=_HTTP_URL.validate_python(
                f"https://raw.githubusercontent.com/{upstream['repository']}/{revision}/{match_asset['key']}"
            ),
            upstream_revision=revision,
            asset_identity=match_asset["sha1"],
            expected_size_bytes=match_asset["size_bytes"],
            rights=rights,
            provider_metadata=metadata,
            upstream_capabilities=tuple(capabilities),
            discovered_at=discovered,
            availability_state=SourceCatalogState.UPSTREAM_AVAILABLE,
        )
        entries.append(contest)
    teams = tuple(sorted(set(team_ids.values())))
    for aggregate in corpus["aggregates"]:
        asset = aggregate["asset"]
        family = aggregate["family"]
        metadata = {
            "aggregate_family": family,
            "source_file_key": asset["key"],
            "source_population_rows": aggregate["source_population_rows"],
            "distinct_player_count": aggregate["distinct_player_count"],
            "distinct_team_count": aggregate["distinct_team_count"],
            "provider_identity_columns": ["player_id", "team_id", "season_id"],
            "position_group_is_a_grain_axis": True,
        }
        entry = SourceCatalogEntry(
            entry_id=skillcorner_aggregate_catalog_id(edition_id, family),
            provider=source.provider,
            dataset=source.dataset_id,
            external_id=f"aggregate:{edition_id}:{family}",
            object_kind=SourceObjectKind.AGGREGATE,
            registry_dataset_id=DATASET_ID,
            registry_version=revision,
            registry_file_key=asset["key"],
            sport_id="football",
            competition_id=competition_id,
            competition_edition_id=edition_id,
            teams=teams,
            upstream_url=_HTTP_URL.validate_python(
                f"https://raw.githubusercontent.com/{upstream['repository']}/{revision}/{asset['key']}"
            ),
            upstream_revision=revision,
            asset_identity=asset["sha1"],
            expected_size_bytes=asset["size_bytes"],
            rights=rights,
            provider_metadata=metadata,
            upstream_capabilities=("SEASON_AGGREGATE",),
            discovered_at=discovered,
            availability_state=SourceCatalogState.UPSTREAM_AVAILABLE,
        )
        entries.append(entry)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        row = entry.model_dump(mode="python")
        row["upstream_url"] = str(entry.upstream_url)
        row["object_kind"] = entry.object_kind.value
        row["availability_state"] = entry.availability_state.value
        row["teams"] = list(entry.teams)
        row["upstream_capabilities"] = list(entry.upstream_capabilities)
        rows.append(row)
    return rows


def build_skillcorner_catalog_rows(corpus: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build canonical league/contest semantics with no session or dense artifact writes."""
    upstream = corpus["upstream"]
    revision = upstream["revision"]
    authority = f"SkillCorner matches.json and match.json@{revision}"
    competition_id = canonical_sports_id(
        NAMESPACE, SportsEntityKind.COMPETITION, upstream["competition"]["provider_id"]
    )
    edition_id = canonical_sports_id(
        NAMESPACE, SportsEntityKind.EDITION, upstream["competition_edition"]["provider_id"]
    )
    rows: dict[str, list[dict[str, Any]]] = {
        "sport": [{"sport_id": "football", "code": "football", "display_name": "Football"}],
        "competition": [
            {
                "competition_id": competition_id,
                "sport_id": "football",
                "name": upstream["competition"]["name"],
            }
        ],
        "competition_edition": [
            {
                "edition_id": edition_id,
                "competition_id": competition_id,
                "label": upstream["season"]["label"],
                "kind": EditionKind.LEAGUE_SEASON.value,
            }
        ],
        "team": [],
        "contest": [],
        "contest_team": [],
        "contest_period": [],
        "provider_identity_crosswalk": [],
    }
    rows["provider_identity_crosswalk"].extend(
        (
            _provider_crosswalk_row(
                SportsEntityKind.COMPETITION,
                upstream["competition"]["provider_id"],
                source_authority=authority,
                metadata={"name": upstream["competition"]["name"]},
            ),
            _provider_crosswalk_row(
                SportsEntityKind.EDITION,
                upstream["competition_edition"]["provider_id"],
                source_authority=authority,
                metadata={"label": upstream["season"]["label"]},
            ),
        )
    )
    team_ids: dict[str, str] = {}
    for source_team in corpus["teams"]:
        provider_id = str(source_team["provider_team_id"])
        team_id = _canonical_team(provider_id)
        team_ids[provider_id] = team_id
        rows["team"].append(
            {
                "team_id": team_id,
                "sport_id": "football",
                "display_name": source_team["display_name"],
            }
        )
        rows["provider_identity_crosswalk"].append(
            _provider_crosswalk_row(
                SportsEntityKind.TEAM,
                provider_id,
                source_authority=authority,
                metadata={"short_name": source_team.get("short_name")},
            )
        )
    for match in corpus["matches"]:
        match_id = str(match["id"])
        detail = match["detail"]
        contest_id = canonical_sports_id(NAMESPACE, SportsEntityKind.CONTEST, match_id)
        home_id = str(match["home_team"]["id"])
        away_id = str(match["away_team"]["id"])
        rows["contest"].append(
            {
                "contest_id": contest_id,
                "sport_id": "football",
                "competition_edition_id": edition_id,
                "scheduled_start_at": datetime.fromisoformat(
                    match["date_time"].replace("Z", "+00:00")
                ),
                "actual_start_at": datetime.fromisoformat(
                    detail["date_time"].replace("Z", "+00:00")
                ),
                "venue": detail["stadium"].get("name")
                if isinstance(detail.get("stadium"), dict)
                else detail.get("stadium"),
                "home_away_supported": True,
                "source_authority": authority,
            }
        )
        rows["contest_team"].extend(
            (
                {
                    "contest_id": contest_id,
                    "team_id": team_ids[home_id],
                    "side": ContestSide.HOME.value,
                    "side_order": 0,
                    "score": detail.get("home_team_score"),
                },
                {
                    "contest_id": contest_id,
                    "team_id": team_ids[away_id],
                    "side": ContestSide.AWAY.value,
                    "side_order": 1,
                    "score": detail.get("away_team_score"),
                },
            )
        )
        for period in detail.get("match_periods", []):
            number = str(period["period"])
            rows["contest_period"].append(
                {
                    "contest_period_id": f"{contest_id}:period:{number}",
                    "contest_id": contest_id,
                    "source_period_number": number,
                    "kind": PeriodKind.HALF.value
                    if number in {"1", "2"}
                    else PeriodKind.OTHER.value,
                    "label": period.get("name"),
                    "provider_namespace": NAMESPACE,
                    "start_ns": None,
                    "end_ns": None,
                }
            )
        rows["provider_identity_crosswalk"].append(
            _provider_crosswalk_row(
                SportsEntityKind.CONTEST,
                match_id,
                source_authority=authority,
                metadata={"matches_json_status": match["status"]},
            )
        )
    return rows


def register_skillcorner_corpus(*, verify_upstream: bool = True) -> dict[str, Any]:
    """Register the metadata-first contest catalog; never downloads source assets."""
    corpus = load_corpus_manifest()
    registry = validate_registry()
    source = source_by_id(registry, DATASET_ID)
    try:
        source.version(corpus["upstream"]["revision"])
    except KeyError as exc:
        raise ValueError("SkillCorner corpus revision is absent from the source registry") from exc
    upstream_receipt = None
    if verify_upstream:
        with requests.Session() as http:
            upstream_receipt = validate_upstream_corpus(corpus=corpus, session=http)
    from dynamis.pipeline.persist import persist_skillcorner_corpus, persist_source

    resolved = settings()
    engine = control_plane_engine(resolved)
    try:
        with engine.begin() as connection:
            base_rows = persist_source(connection, source)
            corpus_rows = persist_skillcorner_corpus(connection, source, corpus)
    finally:
        engine.dispose()
    rows_written = dict(base_rows)
    for key, count in corpus_rows.items():
        rows_written[key] = rows_written.get(key, 0) + count
    return {
        "dataset_id": DATASET_ID,
        "revision": corpus["upstream"]["revision"],
        "matches": len(corpus["matches"]),
        "teams": len(corpus["teams"]),
        "contest_entries": len(corpus["matches"]),
        "season_aggregate_entries": len(corpus["aggregates"]),
        "upstream_validation": upstream_receipt,
        "dense_bytes_downloaded": 0,
        "rows_written": rows_written,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dynamis-register-skillcorner-corpus",
        description=(
            "Register the pinned SkillCorner contest catalog without acquiring dense assets."
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--skip-upstream-validation",
        action="store_true",
        help="Use the committed pinned manifest without checking GitHub/Hugging Face metadata.",
    )
    args = parser.parse_args(argv)
    try:
        result = register_skillcorner_corpus(verify_upstream=not args.skip_upstream_validation)
    except (
        ConfigurationError,
        OSError,
        RegistryError,
        ValueError,
        requests.RequestException,
    ) as exc:
        print(f"dynamis-register-skillcorner-corpus: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"registered {result['matches']} matches and {result['teams']} teams "
            f"at upstream revision {result['revision']}; "
            f"{result['dense_bytes_downloaded']} dense bytes downloaded"
        )
    return 0
