# RES-112 acceptance matrix

Acceptance authority order (RES-112 kickoff): **1** real local browser behaviour · **2** scientific
and data contracts · **3** focused regression tests · **4** full automated matrix · **5**
fixed-viewport visual evidence. A row passes only when every listed gate passes; a unit test never
overrides a visible broken state.

Gate legend: **R** real-data Playwright (`apps/web/e2e-real`, no interception) · **F**
deterministic fixture Playwright (`apps/web/e2e`) · **U** Vitest · **B** backend pytest ·
**V** fixed-viewport screenshot reviewed by eye · **M** manual browser check recorded here.

Status: `pending` before repair; each row is updated with the verifying commit/run.

## Field — data and materialization

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-D1 | DFL Level A/B/C/D artifacts registered for both periods; `GET /api/tactical/artifacts` non-empty per level | B R | D-01 | pending |
| AF-D2 | SkillCorner Level A/B/C registered; Level D/E explicitly unavailable with capability reason | B R | D-02 | pending |
| AF-D3 | Rerunning preparation is deterministic (same run ids / series checksums) | B | D-04 | pending |
| AF-D4 | Locomotor metrics exist only for athlete entities; no ball/official locomotor metric served | B R | D-03 | pending |
| AF-D5 | Tactical series ETag round-trip returns 304 for an identical request | B | — | pending |
| AF-D6 | `dynamis-demo-prepare --check` fails loudly (non-zero, named artifact) when a required local source or artifact is missing | B | D-04 | pending |

## Field — playback, time and selection

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-P1 | Opening Field without `t_ns` lands on the stream's first canonical frame; transport, header, footer and pane agree | R F U | F-01 | pending |
| AF-P2 | DFL Play advances; reverse returns; pause commits `t_ns` | R F U | F-02 | pending |
| AF-P3 | Seek via timeline to an arbitrary time in a later chunk renders that exact frame | R F | S-01 | pending |
| AF-P4 | Playback across ≥2 chunk boundaries forward and reverse keeps one Pixi application (no WebGL context churn) | R U | F-03 | pending |
| AF-P5 | Tactical API requests during 5 s of playback are bounded by chunk handoffs, not frames | R | T-02 | pending |
| AF-P6 | Selecting a player/ball persists across chunk handoff; does not write the Pose subject key; no history push per click | R U | F-06 | pending |
| AF-P7 | Range commit/clear keeps trails and Range tab consistent | R F | T-05 | pending |
| AF-P8 | Event seek (Events tab) moves the playhead to the event's canonical time | R | T-06 | pending |

## Field — tactical overlays

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-O1 | Hull/territory drawn for the exact current canonical frame (geometry rows share `t_rel_ns` with drawn entities) | R U | F-04 | pending |
| AF-O2 | Influence grid shows the most recent grid at or before the playhead and discloses its time | R U | F-04 | pending |
| AF-O3 | Overlay colour per team equals that team's entity colour on DFL and SkillCorner | R U | F-05 | pending |
| AF-O4 | Semantic layer order; ball and selection drawn above all overlays | U V | F-07 | pending |
| AF-O5 | Default layers: Hull on, Territory/Influence off; toggles live without renderer rebuild | R U | F-07 | pending |
| AF-O6 | Zoom/pan/reset stable with overlays on | M | — | pending |

## Field — Tactical Analysis pane

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-T1 | Live: per-team values for the current frame, team label, units, measurement class | R F | T-03 | pending |
| AF-T2 | Space: territory (deterministic) and influence (model) per team at current frame, with class labels | R F | T-04 | pending |
| AF-T3 | Shape: scientifically explicit unavailable state citing the capability | R F | — | pending |
| AF-T4 | Range: per-team series over the committed range, or an explicit "commit a range" state | R F | T-05 | pending |
| AF-T5 | Events: DFL source-event snapshots list and seek; SkillCorner explicit unsupported state | R F | T-06 | pending |
| AF-T6 | Report: deterministic JSON including artifact ids, run ids, parameter hashes, window | R F | T-08 | pending |
| AF-T7 | Missing materialization, unsupported capability, no-row-at-time, loading and API failure are visibly different states | F U | T-01, T-07 | pending |
| AF-T8 | Tab switch leaves no stale content; tabs single-line at 1366 px; arrow-key navigation | R F | T-08 | pending |

## Pose

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AP-1 | Opening Pose without `t_ns` lands on the subject's first observation; transport agrees | R F | P-01 | pending |
| AP-2 | Subject switch while paused, while playing, while buffering and after >10 s lands on an exact observation; no previous-subject request after the switch | R F | — | pending |
| AP-3 | Back/forward and reload restore subject + time | R | — | pending |
| AP-4 | Body-local ↔ match/world ↔ all-subjects transitions never produce contradictory control states | R U | P-03 | pending |
| AP-5 | Every camera mode reachable and releasing to manual never fights follow | M R | P-03 | pending |
| AP-6 | Layer toggles apply live and stay frame-synchronized during playback | R | P-06 | pending |
| AP-7 | Long playback (≥30 s) across chunk boundaries without scene-bound blow-up or console errors | R | — | pending |
| AP-8 | Skeleton recognizable at 1440×900; selected joint and subject unambiguous in all-subject mode | V | P-02, P-04 | pending |
| AP-9 | Telemetry shows the selected subject at the current time with observed/unavailable distinction | R | — | pending |

## Whole system

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AS-1 | Catalog, Overview, Signals, Compare, Methods, Quality, Runs load against real API without console errors | R | — | pending |
| AS-2 | Lab deep link to an unavailable view resolves to an available one | F U | S-02 | pending |
| AS-3 | Overview charts/table readable (no overlapping labels, no clipped class) | V | S-03 | pending |
| AS-4 | Human labels (team name, shirt/name) lead; ids secondary and copyable | R V | S-07 | pending |
| AS-5 | 1600×1000, 1440×900, 1366×768: no horizontal document scroll; no clipped flagship controls | R F | S-04 | pending |
| AS-6 | axe: no serious/critical violations on flagship routes (real data) | R F | — | pending |
| AS-7 | Keyboard: tab order, visible focus, tactical tabs arrow keys, transport shortcuts | M F | — | pending |
| AS-8 | Reduced motion respected | F | — | pending |
| AS-9 | Runs page distinguishes series-producing tactical runs from metric runs | R V | S-06 | pending |
| AS-10 | Catalog laboratory chips reflect accepted local capability | R | S-05 | pending |

## Console allow-list

Only these messages are tolerated on flagship paths, each with a recorded justification:

| message | source | justification |
| --- | --- | --- |
| `THREE.Clock: This module has been deprecated` | R3F/three upstream | dependency warning, recorded since RES-108 (FP-02) |
| `GL Driver Message … GPU stall due to ReadPixels` | Chromium | emitted while Playwright reads a WebGL canvas (FP-02) |

Any `console.error` or `pageerror` fails acceptance.

## Final seal (issue §16)

| gate | command | result |
| --- | --- | --- |
| Python suite | `uv run pytest` | pending |
| PostgreSQL suite | `uv run pytest -m postgres` | pending |
| Ruff | `uv run ruff check . && uv run ruff format --check .` | pending |
| Pyright | `uv run pyright` | pending |
| Registry/rights | `uv run dynamis-registry-validate` | pending |
| Repository guard | `uv run python scripts/guard_repository.py` | pending |
| Architecture contract | `uv run python scripts/validate_architecture.py` | pending |
| OpenAPI drift | `pnpm run web:api-check` | pending |
| TypeScript | `pnpm run web:typecheck` | pending |
| ESLint | `pnpm run web:lint` | pending |
| Vitest | `pnpm run web:test` | pending |
| Production build | `pnpm run web:build` | pending |
| Playwright (fixtures, axe, renderer, responsive, lazy) | `pnpm run web:e2e` | pending |
| Real-data Field/Pose acceptance | `pnpm --filter @dynamis/web run test:e2e:real` | pending |
