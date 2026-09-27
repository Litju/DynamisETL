"""Record RES-122 real-data acceptance against the running local API.

Usage: uv run python scripts/res122_acceptance.py [--base http://127.0.0.1:8765]
Writes output/res-122/acceptance.json. Reads metadata and one bounded game per
sport; it never triggers acquisition.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from typing import Any

from dynamis.adapters.sportsdataverse.releases import load_snapshot
from dynamis.config import repository_root


def _get(base: str, path: str) -> tuple[Any, int, float]:
    started = time.perf_counter()
    with urllib.request.urlopen(base + path) as response:
        body = response.read()
    return json.loads(body), len(body), round((time.perf_counter() - started) * 1000, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    snapshot = load_snapshot()
    editions, _, _ = _get(args.base, "/api/games/editions")
    receipt: dict[str, Any] = {
        "snapshot": snapshot["snapshot"],
        "release_families_catalogued": snapshot["family_count"],
        "pinned_assets": [
            {key: item[key] for key in ("key", "asset_id", "size_bytes", "updated_at")}
            for item in snapshot["pinned"]
        ],
        "editions": [],
    }
    for edition in editions:
        page, _, list_ms = _get(
            args.base, f"/api/games?edition_id={edition['edition_id']}&limit=50&offset=0"
        )
        game = next(row for row in page["rows"] if row["completed"])
        detail, detail_bytes, detail_ms = _get(args.base, f"/api/games/{game['contest_id']}")
        plays, plays_bytes, plays_ms = _get(
            args.base, f"/api/games/{game['contest_id']}/plays?limit=500"
        )
        last, _, _ = _get(
            args.base, f"/api/games/{game['contest_id']}/plays?limit=1&offset={plays['total'] - 1}"
        )
        box, box_bytes, box_ms = _get(args.base, f"/api/games/{game['contest_id']}/box")
        final_state = {
            key: last["rows"][0]["attributes"].get(key) for key in ("home_score", "away_score")
        }
        teams = {team["side"]: team for team in game["teams"]}
        receipt["editions"].append(
            {
                "sport": edition["sport_name"],
                "competition": edition["competition_name"],
                "edition": edition["edition_label"],
                "contests": edition["contest_count"],
                "families": {
                    family["family"]: {
                        "grain": family["grain_kind"],
                        "rows": family["row_count"],
                        "checksum_sha256": family["checksum_sha256"],
                        "release_asset_id": family["release_asset_id"],
                    }
                    for family in edition["families"]
                },
                "score_reconciliation": edition["score_reconciliation"],
                "local_only": edition["license"]["local_only"],
                "sample_game": {
                    "provider_game_id": game["provider_game_id"],
                    "home": teams["home"]["display_name"],
                    "away": teams["away"]["display_name"],
                    "final": [teams["home"]["score"], teams["away"]["score"]],
                    "pbp_final_state": [final_state["home_score"], final_state["away_score"]],
                    "periods": [
                        {key: period[key] for key in ("number", "kind", "label", "event_count")}
                        for period in detail["periods"]
                    ],
                    "plays_total": plays["total"],
                    "attributes_schema": plays["rows"][0]["attributes_schema_id"],
                    "box_families": [
                        {"family": family["family"], "rows": len(family["rows"])}
                        for family in box["families"]
                    ],
                    "latency_ms": {
                        "list": list_ms,
                        "detail": detail_ms,
                        "plays_500": plays_ms,
                        "box": box_ms,
                    },
                    "bytes": {"detail": detail_bytes, "plays_500": plays_bytes, "box": box_bytes},
                },
            }
        )
    out = repository_root() / "output" / "res-122" / "acceptance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
