"""SportsDataverse release discovery and the pinned release snapshot.

Discovery reads GitHub *release metadata* only (tags, assets, sizes, ids, update
times) plus each pinned family's tiny ``timestamp.json``/``package_function.json``
freshness files. No dataset payload is fetched. The result is committed as
``sources/sportsdataverse-releases.json``; it is the authority the resolver checks
an acquisition against, because GitHub release assets can be replaced in place.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from dynamis.acquisition.download import USER_AGENT
from dynamis.adapters.sportsdataverse.taxonomy import (
    TAXONOMY_VERSION,
    asset_season,
    map_family,
)
from dynamis.config import repository_root

DATASET_ID = "sportsdataverse"
REPOSITORY = "sportsdataverse/sportsdataverse-data"
RELEASES_API = f"https://api.github.com/repos/{REPOSITORY}/releases"
RELEASE_TAG_API = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{{tag}}"
DOWNLOAD_URL = f"https://github.com/{REPOSITORY}/releases/download/{{tag}}/{{name}}"
SNAPSHOT_SCHEMA_VERSION = 1

#: The bounded acceptance slice: one NBA season and one NHL season. Nothing else
#: is ever pinned for acquisition by default.
PINNED_ASSETS: tuple[tuple[str, str], ...] = (
    ("espn_nba_schedules", "nba_schedule_2026.parquet"),
    ("espn_nba_pbp", "play_by_play_2026.parquet"),
    ("espn_nba_player_boxscores", "player_box_2026.parquet"),
    ("espn_nba_team_boxscores", "team_box_2026.parquet"),
    ("nhl_schedules", "nhl_schedule_2026.parquet"),
    ("nhl_pbp_lite", "play_by_play_lite_2026.parquet"),
    ("nhl_skater_boxscores", "skater_box_2026.parquet"),
    ("nhl_goalie_boxscores", "goalie_box_2026.parquet"),
    ("nhl_team_boxscores", "team_box_2026.parquet"),
)

FRESHNESS_FILES = ("timestamp.json", "package_function.json")


class SnapshotError(ValueError):
    """The committed release snapshot is missing, malformed or inconsistent."""


def default_snapshot_path() -> Path:
    return repository_root() / "sources" / "sportsdataverse-releases.json"


def pinned_key(tag: str, name: str) -> str:
    return f"{tag}/{name}"


def _api_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get(session: requests.Session, url: str, *, params: Mapping[str, Any] | None = None) -> Any:
    response = session.get(url, params=params, timeout=(15.0, 60.0), headers=_api_headers())
    try:
        if not response.ok:
            raise SnapshotError(
                f"GitHub metadata request failed with {response.status_code}: {url}"
            )
        return response.json()
    finally:
        response.close()


def list_releases(session: requests.Session) -> list[dict[str, Any]]:
    """Every release of the data repository, following pagination."""
    releases: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _get(session, RELEASES_API, params={"per_page": 100, "page": page})
        if not isinstance(batch, list):
            raise SnapshotError("GitHub releases API did not return a list")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def _family_row(release: Mapping[str, Any]) -> dict[str, Any]:
    tag = str(release["tag_name"])
    mapping = map_family(tag)
    parquet: list[list[Any]] = []
    formats: set[str] = set()
    seasons: set[int] = set()
    total = 0
    for asset in release.get("assets", []):
        name = str(asset["name"])
        size = int(asset["size"])
        total += size
        parsed = asset_season(name)
        if parsed is None:
            continue
        season, fmt = parsed
        formats.add(fmt)
        seasons.add(season)
        if fmt == "parquet":
            parquet.append([name, season, size, int(asset["id"])])
    return {
        "tag": tag,
        "release_id": int(release["id"]),
        "published_at": release.get("published_at"),
        "asset_count": len(release.get("assets", [])),
        "total_bytes": total,
        "formats": sorted(formats),
        "seasons": sorted(seasons),
        "league_id": mapping.league_id,
        "sport_id": mapping.sport_id,
        "competition_name": mapping.competition_name,
        "family_kind": mapping.family_kind,
        "grain": mapping.grain.value if mapping.grain else None,
        "rule": mapping.rule,
        # [asset name, season, size bytes, asset id]; parquet only, sorted.
        "parquet_assets": sorted(parquet, key=lambda item: (item[1], item[0])),
    }


def _freshness(
    session: requests.Session, tag: str, assets: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    names = {str(asset["name"]) for asset in assets}
    found: dict[str, Any] = {}
    for name in FRESHNESS_FILES:
        if name not in names:
            continue
        response = session.get(
            DOWNLOAD_URL.format(tag=tag, name=name),
            timeout=(15.0, 60.0),
            headers={"User-Agent": USER_AGENT},
        )
        try:
            if response.ok and len(response.content) < 64_000:
                found[name.removesuffix(".json")] = response.json()
        finally:
            response.close()
    return found


def discover(
    session: requests.Session,
    *,
    snapshot: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the release snapshot from live GitHub release metadata."""
    releases = list_releases(session)
    by_tag = {str(release["tag_name"]): release for release in releases}
    pinned: list[dict[str, Any]] = []
    for tag, name in PINNED_ASSETS:
        release = by_tag.get(tag)
        if release is None:
            raise SnapshotError(f"pinned family {tag!r} is not a live release")
        asset = next((item for item in release["assets"] if item["name"] == name), None)
        if asset is None:
            raise SnapshotError(f"pinned asset {tag}/{name} is not in the live release")
        mapping = map_family(tag)
        parsed = asset_season(name)
        pinned.append(
            {
                "key": pinned_key(tag, name),
                "tag": tag,
                "asset_name": name,
                "asset_id": int(asset["id"]),
                "size_bytes": int(asset["size"]),
                "updated_at": asset["updated_at"],
                "content_type": asset.get("content_type"),
                "download_url": asset["browser_download_url"],
                "league_id": mapping.league_id,
                "sport_id": mapping.sport_id,
                "family_kind": mapping.family_kind,
                "grain": mapping.grain.value if mapping.grain else None,
                "season": parsed[0] if parsed else None,
                "freshness": _freshness(session, tag, release["assets"]),
            }
        )
    families = sorted((_family_row(release) for release in releases), key=lambda row: row["tag"])
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "repository": REPOSITORY,
        "snapshot": snapshot,
        "discovered_at": (now or datetime.now(UTC)).replace(microsecond=0).isoformat(),
        "taxonomy_version": TAXONOMY_VERSION,
        "authority": (
            "GitHub Releases API metadata for sportsdataverse/sportsdataverse-data; "
            "README text is not release authority"
        ),
        "family_count": len(families),
        "families": families,
        "pinned": pinned,
    }


@dataclass(frozen=True, slots=True)
class PinnedAsset:
    key: str
    tag: str
    asset_name: str
    asset_id: int
    size_bytes: int
    updated_at: str
    league_id: str
    sport_id: str
    family_kind: str
    grain: str | None
    season: int
    freshness: Mapping[str, Any]


def load_snapshot(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the committed release snapshot."""
    source = path or default_snapshot_path()
    try:
        snapshot = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"cannot load SportsDataverse snapshot {source}: {exc}") from exc
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotError("unsupported SportsDataverse snapshot schema")
    if snapshot.get("dataset_id") != DATASET_ID or snapshot.get("repository") != REPOSITORY:
        raise SnapshotError("snapshot does not describe the SportsDataverse data repository")
    if snapshot.get("taxonomy_version") != TAXONOMY_VERSION:
        raise SnapshotError(
            f"snapshot taxonomy {snapshot.get('taxonomy_version')!r} != {TAXONOMY_VERSION!r}; "
            "rediscover under the current rules"
        )
    families = snapshot.get("families")
    if not isinstance(families, list) or len(families) != snapshot.get("family_count"):
        raise SnapshotError("snapshot family inventory is inconsistent")
    tags = [family["tag"] for family in families]
    if len(tags) != len(set(tags)):
        raise SnapshotError("snapshot contains duplicate release tags")
    for family in families:
        mapping = map_family(family["tag"])
        if mapping.rule != family["rule"]:
            raise SnapshotError(f"{family['tag']}: stored rule differs from the taxonomy")
    pinned = snapshot.get("pinned")
    expected = [pinned_key(tag, name) for tag, name in PINNED_ASSETS]
    if not isinstance(pinned, list) or [item.get("key") for item in pinned] != expected:
        raise SnapshotError("snapshot pins must be exactly the bounded NBA/NHL acceptance slice")
    return snapshot


def pinned_assets(snapshot: Mapping[str, Any]) -> tuple[PinnedAsset, ...]:
    return tuple(
        PinnedAsset(
            key=item["key"],
            tag=item["tag"],
            asset_name=item["asset_name"],
            asset_id=int(item["asset_id"]),
            size_bytes=int(item["size_bytes"]),
            updated_at=str(item["updated_at"]),
            league_id=str(item["league_id"]),
            sport_id=str(item["sport_id"]),
            family_kind=str(item["family_kind"]),
            grain=item.get("grain"),
            season=int(item["season"]),
            freshness=item.get("freshness", {}),
        )
        for item in snapshot["pinned"]
    )


def write_snapshot(snapshot: Mapping[str, Any], path: Path | None = None) -> Path:
    """Write the snapshot with one release family / pinned asset per line.

    Stable key order and one entity per line keep refreshes reviewable as diffs.
    """
    target = path or default_snapshot_path()

    def compact(value: Any) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    lines = ["{"]
    keys = sorted(snapshot)
    for index, key in enumerate(keys):
        value = snapshot[key]
        comma = "," if index < len(keys) - 1 else ""
        if key in {"families", "pinned"}:
            items = ",\n".join(f"  {compact(item)}" for item in value)
            lines.append(f' "{key}": [\n{items}\n ]{comma}')
        else:
            lines.append(f' "{key}": {compact(value)}{comma}')
    lines.append("}")
    target.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dynamis-sdv-discover",
        description="Discover SportsDataverse release metadata (no dataset payload).",
    )
    parser.add_argument("--snapshot", required=True, help="snapshot label, e.g. sdv-2026-09-27")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    with requests.Session() as session:
        snapshot = discover(session, snapshot=args.snapshot)
    target = write_snapshot(snapshot, args.out)
    print(
        f"{snapshot['family_count']} release families, {len(snapshot['pinned'])} pinned assets "
        f"-> {target}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
