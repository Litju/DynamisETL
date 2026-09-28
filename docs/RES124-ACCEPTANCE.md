# RES-124 acceptance

Source is pinned to SkillCorner Open Data for Basketball revision
`4bbed2e35e8fdd2cf083e8c8b280b3e5381a2c66`. The provider documents 25 Hz
tracking, center-origin coordinates in feet, period-scoped frame/wall/game clocks,
and clock-only dead-time frames in its
[tracking dictionary](https://github.com/SkillCorner/opendata-basketball/blob/4bbed2e35e8fdd2cf083e8c8b280b3e5381a2c66/docs/data_dictionary/tracking_data.md).
The pinned
[aggregate column reference](https://github.com/SkillCorner/opendata-basketball/blob/4bbed2e35e8fdd2cf083e8c8b280b3e5381a2c66/docs/aggregates_columns.md)
defines the Shots, Drives, and Picks denominator semantics, offense-only scope,
coverage, and provider total-row convention.

## Population and spatial reference

The metadata catalog contains 10 sample games representing 17 distinct teams.
The three season aggregate files each cover 18 teams and 293 of 327 ACB games.
The aggregate catalog records that separate 18-team population without reusing
the 17-team sample-game list.
SeasonLab's Metric evidence panel visibly states that the aggregates are
offense-only and distinguishes the 17 sample-game teams from the 18-team season
population.

The source `SpatialReference` is
`skillcorner-basketball-court-ft` (`ft`) with a declared unit-scale transform
`ft → m` at `0.3048`; the canonical tracking frame is
`skillcorner-basketball-court-m`. A real period-1 frame (`frameIdx=832`) checked
all 10 players and the ball against the pinned Bronze source and Silver
coordinates. Converting to metres and back recovered all 11 source points with
maximum error `0.0 ft`.

## Reconciliation for the materialized game

Game `114243` contains 146,870 source frames at 25 Hz, including 69,847 dead-time
frames. Every one of its 7,346 Dynamic Events has a recorded disposition:

| Family | Events | Exact frame | Exact time/clock | Legitimately unlinked |
| --- | ---: | ---: | ---: | ---: |
| `chance_players` | 2,160 | 0 | 0 | 2,160 |
| `chances` | 216 | 215 | 0 | 1 |
| `closeouts` | 58 | 58 | 0 | 0 |
| `dribbles` | 1,234 | 1,234 | 0 | 0 |
| `drives` | 58 | 58 | 0 | 0 |
| `fouls` | 40 | 40 | 0 | 0 |
| `free_throws` | 36 | 36 | 0 | 0 |
| `handoffs` | 56 | 56 | 0 | 0 |
| `isolations` | 11 | 11 | 0 | 0 |
| `matchups` | 1,497 | 1,497 | 0 | 0 |
| `off_ball_screens` | 136 | 136 | 0 | 0 |
| `passes` | 525 | 525 | 0 | 0 |
| `picks` | 135 | 135 | 0 | 0 |
| `possessions` | 157 | 156 | 0 | 1 |
| `posts` | 15 | 15 | 0 | 0 |
| `rebounds` | 95 | 95 | 0 | 0 |
| `shots` | 159 | 159 | 0 | 0 |
| `timeouts` | 5 | 5 | 0 | 0 |
| `touches` | 728 | 728 | 0 | 0 |
| `turnovers` | 25 | 25 | 0 | 0 |
| **Total** | **7,346** | **5,184** | **0** | **2,162** |

The 2,160 `chance_players` rows are relationship records without temporal keys.
The remaining two unlinked rows (one chance and one possession) have no exact
tracking key. No frame is chosen by nearest-time snapping. The real game has no
clock-only links; exact wall-clock and unique period + game-clock/shot-clock
links are covered by focused tests, and ambiguous clock keys stay unlinked.

The complete event-level reconciliation has one JSONL row per source event,
including source keys, disposition, link method, reason, and linked frame/time.
It is kept with the local-only data receipts, not committed as source data:

`DYNAMIS_DATASET_ROOT/cache/receipts/skillcorner-basketball-opendata/res124-acceptance-20260927/event-linkage-reconciliation.jsonl`

SHA-256: `0f5ece4ed2e48c5e6b6ee3f1f27ffaad98dcdddb995ed302b7d5216f2eebbd8a`

## Season aggregate reconciliation

The original provider files remain checksummed in Bronze. Provider teamless
season-total rows are listed by source row, provider player id, and exclusion
reason in both artifact metadata and the aggregate reconciliation receipt.
Traded-player team rows remain canonicalized at player × team grain; provider
player ids remain attached to the canonical rows.

| Family | Source rows | Canonical rows | Teams | Total rows excluded | Alias ids consolidated | Derived fields left null |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Shots | 326 | 313 | 18 | 5 | 8 | 0 |
| Drives | 301 | 289 | 18 | 5 | 7 | 0 |
| Picks | 319 | 306 | 18 | 5 | 8 | 16 |

Rates and efficiencies are merged only with provider-defined denominators:
attempts for shot rates, `total_drives` / `fga_in_drive` for Drives, and role or
same-bucket pick counts for Picks. Two-point and three-point pick percentages
use the corresponding source make + miss counts. Sixteen Picks fields remain
null where an aliased provider row lacks a rate despite a positive or undefined
denominator; the original values remain available in the source Bronze file and
the unsupported field list is recorded in the reconciliation.

## Real browser and regression checks

`apps/web/e2e-real/res124-basketball.spec.ts` passed against the real local API
and Chromium. It seeks a shot, timeout, pick, and drive to their exact frames and
canonical times, checks the 13-entry source-capability response and the
materialized contest's `play_by_play_available` flag, checks both team
populations and the visible SeasonLab caveat, and walks Football MatchLab →
Basketball spatial game → SeasonLab → Football MatchLab. Screenshots are
included with the local acceptance receipt:
`basketball-spatial.png` and `seasonlab-coverage.png`.

| Check | Result |
| --- | --- |
| Ruff check and format | Passed |
| Pyright | 0 errors, 0 warnings |
| OpenAPI generation and TypeScript drift check | Passed |
| Python regressions (including PostgreSQL) | 713 passed |
| Web typecheck and lint | Passed |
| Web production build | Passed |
| Vitest | 207 passed across 37 files |
| Real RES-124 Playwright acceptance | 1 passed |

The build emits a non-failing ECharts chunk-size warning. The court renderer is
separated into `BasketballCourt.tsx`; the remaining adapter files already align
with source catalog, tracking, events, and season-aggregate responsibilities, so
no size-only adapter refactor was needed.
