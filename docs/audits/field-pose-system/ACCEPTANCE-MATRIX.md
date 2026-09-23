# RES-112 acceptance matrix

Acceptance authority order (RES-112 kickoff): **1** real local browser behaviour · **2** scientific
and data contracts · **3** focused regression tests · **4** full automated matrix · **5**
fixed-viewport visual evidence. A row passes only when every listed gate passes; a unit test never
overrides a visible broken state.

Gate legend: **R** real-data Playwright (`apps/web/e2e-real`, no interception) · **F**
deterministic fixture Playwright (`apps/web/e2e`) · **U** Vitest · **B** backend pytest ·
**V** fixed-viewport screenshot reviewed by eye · **M** manual browser check recorded here.

Status: every row was `pending` at the audit commit `2a2499e`; each now names its verifying run.

## Field — data and materialization

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-D1 | DFL Level A/B/C/D artifacts registered for both periods; `GET /api/tactical/artifacts` non-empty per level | B R | D-01 | pass · prepare READY, `tactical.spec.ts` |
| AF-D2 | SkillCorner Level A/B/C registered; Level D/E explicitly unavailable with capability reason | B R | D-02 | pass · prepare READY; SC D/E unsupported in `tactical.spec.ts` |
| AF-D3 | Rerunning preparation is deterministic (same run ids / series checksums) | B | D-04 | pass · second preparation run: every stream `current`, no rerun |
| AF-D4 | Locomotor metrics exist only for athlete entities; no ball/official locomotor metric served | B R | D-03 | pass · `test_locomotor_processor.py`, `test_current_revision_postgres.py`, READY check |
| AF-D5 | Tactical series ETag round-trip returns 304 for an identical request | B | — | pass · existing `test_tactical_serving.py` ETag 304 path unchanged |
| AF-D6 | `dynamis-demo-prepare --check` fails loudly (non-zero, named artifact) when a required local source or artifact is missing | B | D-04 | pass · `--check` exit 1 before preparation (audit), 0 after; exit 2 on missing source |

## Field — playback, time and selection

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-P1 | Opening Field without `t_ns` lands on the stream's first canonical frame; transport, header, footer and pane agree | R F U | F-01 | pass · `field.spec.ts`, `defaults.test.ts` |
| AF-P2 | DFL Play advances; reverse returns; pause commits `t_ns` | R F U | F-02 | pass · `field.spec.ts` DFL playback, fixture reverse suite |
| AF-P3 | Seek via timeline to an arbitrary time in a later chunk renders that exact frame | R F | S-01 | pass · `field.spec.ts` timeline seek |
| AF-P4 | Playback across ≥2 chunk boundaries forward and reverse keeps one Pixi application (no WebGL context churn) | R U | F-03 | pass · `field.spec.ts` 1 canvas; `PitchReplay.test.tsx` |
| AF-P5 | Tactical API requests during 5 s of playback are bounded by chunk handoffs, not frames | R | T-02 | pass · `field.spec.ts` <= 6 tactical reads / 5 s; `performance.json` |
| AF-P6 | Selecting a player/ball persists across chunk handoff; does not write the Pose subject key; no history push per click | R U | F-06 | pass · `field.spec.ts` entity across handoff, no history entry |
| AF-P7 | Range commit/clear keeps trails and Range tab consistent | R F | T-05 | pass · `tactical.spec.ts` Range commit/clear |
| AF-P8 | Event seek (Events tab) moves the playhead to the event's canonical time | R | T-06 | pass · `tactical.spec.ts` event seek |

## Field — tactical overlays

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-O1 | Hull/territory drawn for the exact current canonical frame (geometry rows share `t_rel_ns` with drawn entities) | R U | F-04 | pass · drawn frame = overlay frame (`data-drawn-frame-ns`) |
| AF-O2 | Influence grid shows the most recent grid at or before the playhead and discloses its time | R U | F-04 | pass · `tactical.spec.ts` grid time stated; `tactical-overlay.test.ts` |
| AF-O3 | Overlay colour per team equals that team's entity colour on DFL and SkillCorner | R U | F-05 | pass · `tactical-overlay.test.ts` roles; visual review |
| AF-O4 | Semantic layer order; ball and selection drawn above all overlays | U V | F-07 | pass · renderer layer order; visual review `final/05` |
| AF-O5 | Default layers: Hull on, Territory/Influence off; toggles live without renderer rebuild | R U | F-07 | pass · defaults Hull on; `field.spec.ts` territory toggle live |
| AF-O6 | Zoom/pan/reset stable with overlays on | R | — | pass · `field.spec.ts` zoom/pan/reset: same canvas, frame and overlay |

## Field — Tactical Analysis pane

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AF-T1 | Live: per-team values for the current frame, team label, units, measurement class | R F | T-03 | pass · `tactical.spec.ts` |
| AF-T2 | Space: territory (deterministic) and influence (model) per team at current frame, with class labels | R F | T-04 | pass · `tactical.spec.ts` |
| AF-T3 | Shape: scientifically explicit unavailable state citing the capability | R F | — | pass · `tactical.spec.ts` |
| AF-T4 | Range: per-team series over the committed range, or an explicit "commit a range" state | R F | T-05 | pass · `tactical.spec.ts` |
| AF-T5 | Events: DFL source-event snapshots list and seek; SkillCorner explicit unsupported state | R F | T-06 | pass · `tactical.spec.ts` (DFL list + seek; SC unsupported) |
| AF-T6 | Report: deterministic JSON including artifact ids, run ids, parameter hashes, window | R F | T-08 | pass · `tactical.spec.ts` provenance for A/B/C/D |
| AF-T7 | Missing materialization, unsupported capability, no-row-at-time, loading and API failure are visibly different states | F U | T-01, T-07 | pass · `tactical-pane-model.test.ts`; fixture `acceptance.spec.ts` 2b |
| AF-T8 | Tab switch leaves no stale content; tabs single-line at 1366 px; arrow-key navigation | R F | T-08 | pass · `tactical.spec.ts` arrow keys; 1366 single-line tabs (`final/*-1366x768`) |

## Pose

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AP-1 | Opening Pose without `t_ns` lands on the subject's first observation; transport agrees | R F | P-01 | pass · `pose.spec.ts` |
| AP-2 | Subject switch while paused, while playing, while buffering and after >10 s lands on an exact observation; no previous-subject request after the switch | R F | — | pass · `pose.spec.ts`; fixture RES-109 paused/playing/buffering suites |
| AP-3 | Back/forward and reload restore subject + time | R | — | pass · `pose.spec.ts` back/forward/reload |
| AP-4 | Body-local ↔ match/world ↔ all-subjects transitions never produce contradictory control states | R U | P-03 | pass · `pose-view-state.test.ts` exhaustive; `pose.spec.ts` |
| AP-5 | Every camera mode reachable and releasing to manual never fights follow | M R | P-03 | pass · `pose.spec.ts` manual on drag; fixture camera suite |
| AP-6 | Layer toggles apply live and stay frame-synchronized during playback | R | P-06 | pass · `pose.spec.ts` switches |
| AP-7 | Long playback (≥30 s) across chunk boundaries without scene-bound blow-up or console errors | R | — | pass · `pose.spec.ts` 4x > 25 s, 1 renderer |
| AP-8 | Skeleton recognizable at 1440×900; selected joint and subject unambiguous in all-subject mode | V | P-02, P-04 | pass · visual review `final/08`, `final/09` |
| AP-9 | Telemetry shows the selected subject at the current time with observed/unavailable distinction | R | — | pass · `pose.spec.ts` |

## Whole system

| id | criterion | gates | defects | status |
| --- | --- | --- | --- | --- |
| AS-1 | Catalog, Overview, Signals, Compare, Methods, Quality, Runs load against real API without console errors | R | — | pass · after-audit log: 0 console/page errors on every surface |
| AS-2 | Lab deep link to a view the session has no stream for keeps that view selected and states why | F U | S-02 | pass · fixture `acceptance.spec.ts` 3/4, 8 |
| AS-3 | Overview charts/table readable (no overlapping labels, no clipped class) | V | S-03 | pass · visual review `final/02` |
| AS-4 | Human labels (team name, shirt/name) lead; ids secondary and copyable | R V | S-07 | pass · `tactical.spec.ts` team names; finals |
| AS-5 | 1600×1000, 1440×900, 1366×768: no horizontal document scroll; no clipped flagship controls | R F | S-04 | pass · `visual-evidence.spec.ts` (no overflow at 1366/1440/1600); fixture responsive |
| AS-6 | axe: no serious/critical violations on flagship routes (real data) | R F | — | pass · real `a11y.spec.ts` 11/11; fixture 8/8 |
| AS-7 | Keyboard: tab order, visible focus, tactical tabs arrow keys, transport shortcuts | M F | — | pass · real `a11y.spec.ts` keyboard |
| AS-8 | Reduced motion respected | F | — | pass · real `a11y.spec.ts` reduced motion; Pose camera honours it |
| AS-9 | Runs page distinguishes series-producing tactical runs from metric runs | R V | S-06 | pass · visual review `final/13` |
| AS-10 | Catalog laboratory chips reflect accepted local capability | R | S-05 | pass · `ingested_modalities`; `final/01` |

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
| Python suite | `uv run pytest` | 597 passed (non-PostgreSQL) |
| PostgreSQL suite | `uv run pytest -m postgres` | 17 passed |
| Ruff | `uv run ruff check . && uv run ruff format --check .` | pass (237 files formatted) |
| Pyright | `uv run pyright` | 0 errors |
| Registry/rights | `uv run dynamis-registry-validate` | PASSED |
| Repository guard | `uv run python scripts/guard_repository.py` | PASSED |
| Architecture contract | `uv run python scripts/validate_architecture.py` | PASSED |
| OpenAPI drift | `pnpm run web:api-check` | in sync |
| TypeScript | `pnpm run web:typecheck` | pass |
| ESLint | `pnpm run web:lint` | 0 problems |
| Vitest | `pnpm run web:test` | 29 files, 170 tests passed |
| Production build | `pnpm run web:build` | built |
| Playwright (fixtures, axe, renderer, responsive, lazy) | `pnpm run web:e2e` | 65 passed, 1 skipped (env-gated RES-109 mocked receipt) |
| Real-data Field/Pose acceptance | `pnpm --filter @dynamis/web run test:e2e:real` | 34 passed on the production build (field 8, pose 5, tactical 3, axe/keyboard/motion 11, performance 4, visual 3) |

## Seal receipts

| item | value |
| --- | --- |
| Branch | `codex/res-110-tactical-intelligence` (RES-110 history preserved; RES-112 commits `2a2499e`…HEAD) |
| Preparation receipt | `${DYNAMIS_DATASET_ROOT}/cache/receipts/dynamis-demo/preparation/flagship-prepare.json` sha256 `29aecfb6d1b7e599d289e689b2b07d889043badc106c34d5bbb4ad231ebcd3fb` |
| Readiness check receipt | `…/preparation/flagship-check.json` sha256 `b1bf6739e3f3bbddda63349d98a7b2c5233ed2780d409b184a7759b5d16b93fe` |
| Performance receipt | `output/playwright/res-112/performance.json` sha256 `b63c2125e1f1aeb6399893ad1d8d73a1fb08156fcf110e79c9b957d66984c93d` |
| Accepted inputs | DFL `DFL-MAT-J03WPY` (tracking P1/P2, events), SkillCorner `1925299` (tracking P1/P2, pose P1/P2), checksums in the preparation receipt |

## Performance (production build, real API, headless Chromium)

| path | fps | long tasks | heap | notes |
| --- | ---: | ---: | ---: | --- |
| Field DFL base replay (Hull) | 44 | 0 / 5 s | 22 MB | no API requests during 5 s |
| + Territory | 37 | 1 / 5 s | 22 MB | projected columns |
| + Influence | 30 | 0 / 5 s | 22 MB | |
| combined across chunk boundary | 30 | 2 / 10 s | 22 MB | no duplicate requests |
| playback chunk (20 isolated exact chunks) | — | — | — | p95 125 ms (budget 250) |
| Pose one subject, all layers | 47 | 0 / 5 s | 18 MB | |
| Pose follow camera | 50 | 0 / 5 s | 18 MB | |
| Pose all subjects | 20 | 52 / 5 s | 18 MB | K-01 known limitation |
| Pose subject switch | — | — | — | 397 ms to telemetry on the new subject |
| `/api/catalog/datasets` | — | — | — | ~20 ms warm (R-04) |

Headless Chromium renders WebGL in software, so fps figures are conservative; heap stays far below
the 256 MB playback budget and no RES-109 budget regressed.

## Visual evidence (fixed viewport, real data, production build)

`output/playwright/res-112/final/` (1440×900 unless stated; Field/Pose also at 1600×1000 and
1366×768):

1. `01-catalog` · 2. `02-overview-dfl` · 3. `03-signals-white-cmj` · 4. `04-field-dfl-live` ·
5. `05-field-dfl-space` · 6. `06-field-dfl-events` · 7. `07-field-skillcorner` ·
8. `08-pose-body-local` · 9. `09-pose-all-subjects` · 10. `10-compare` ·
11. `11-methods-provenance` · 12. `12-quality` · 13. `13-runs`.

Before/after pairs for each visual defect are listed in `DEFECT-REGISTER.md` → Resolution; the
before and after audit sets use the identical harness (`e2e-real/audit-capture.spec.ts`).

## Known limitations

- **K-01** Pose all-subject playback decodes JSON chunks on the main thread (measured above);
  Arrow-worker transport for Pose is recommended with RES-111.
- **SCI-01** Positions, possession and SkillCorner attacking direction exist in Bronze but are not
  part of the RES-110 capability authority; phase-, unit- and zone-based tactical metrics need a
  frozen contract before they can be served. No such value is shown or implied.
- Development servers run React StrictMode, which double-mounts once on load (one duplicate
  request in dev); the production build shows none.
- Fixture test `res109-real-data.spec.ts` stays env-gated (skipped) as in RES-109; the no-mock
  `e2e-real/` suite is the real-data authority.
