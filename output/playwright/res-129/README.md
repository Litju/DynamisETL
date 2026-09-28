# RES-129 first live football slice

Captured from the production Vite build at 1366×768, 1440×900, and 1600×1000. The browser proxy forwarded /api requests to the local serving API; no fixtures were used.

## Live catalog evidence

The RES-125 /api/catalog/read-model returned A-League 2024/2025 with 20 contests: 4 ready and 16 upstream-only. The selected ready SkillCorner resource is Brisbane Roar FC 0–1 Perth Glory Football Club (skillcorner-opendata, session 1925299) and its MatchLab route is ready.

## Request and chunk measurements

| Viewport | API requests before Match World | Dense before World | API requests through World | Dense after World |
| --- | ---: | ---: | ---: | ---: |
| 1366×768 | 6 | 0 | 22 | 6 |
| 1440×900 | 6 | 0 | 22 | 6 |
| 1600×1000 | 6 | 0 | 22 | 6 |

The six dense requests occur after entering Match World: four artifact windows and two tactical series. Research, Data, and Library have no static import paths to Three/R3F/ECharts chunks. Their bundle-manifest static closures report zero heavy chunks.

Production JavaScript loaded before Match World: 40 assets, 1,166,327 raw bytes (374,599 gzip-equivalent bytes). Match World adds 18 assets, 1,368,200 raw bytes (368,451 gzip-equivalent bytes); the largest is View-YjPNc8A4.js at 895,184 bytes (235,152 gzip-equivalent). The separate ECharts chunk is not requested by this slice. Per-viewport reports include each route's loaded chunks and API paths.

Back returned to the exact ready-filter catalog URL: /data/edition/edition-ebf871f2a9cd29912d68880e?status=ready.

## Screenshots

| Step | 1366×768 | 1440×900 | 1600×1000 |
| --- | --- | --- | --- |
| Research Home | [01](final/1366x768/01-research-home.png) | [01](final/1440x900/01-research-home.png) | [01](final/1600x1000/01-research-home.png) |
| Data Browser | [02](final/1366x768/02-data-browser.png) | [02](final/1440x900/02-data-browser.png) | [02](final/1600x1000/02-data-browser.png) |
| Sports | [03](final/1366x768/03-sports.png) | [03](final/1440x900/03-sports.png) | [03](final/1600x1000/03-sports.png) |
| Football | [04](final/1366x768/04-football.png) | [04](final/1440x900/04-football.png) | [04](final/1600x1000/04-football.png) |
| A-League 2024/25 | [05](final/1366x768/05-a-league-2024-25.png) | [05](final/1440x900/05-a-league-2024-25.png) | [05](final/1600x1000/05-a-league-2024-25.png) |
| Ready SkillCorner match | [06](final/1366x768/06-ready-skillcorner-match.png) | [06](final/1440x900/06-ready-skillcorner-match.png) | [06](final/1600x1000/06-ready-skillcorner-match.png) |
| Match World | [07](final/1366x768/07-match-world.png) | [07](final/1440x900/07-match-world.png) | [07](final/1600x1000/07-match-world.png) |
| Back to exact catalog context | [08](final/1366x768/08-back-exact-catalog-context.png) | [08](final/1440x900/08-back-exact-catalog-context.png) | [08](final/1600x1000/08-back-exact-catalog-context.png) |
| Research recent context | [09](final/1366x768/09-research-home-recent.png) | [09](final/1440x900/09-research-home-recent.png) | [09](final/1600x1000/09-research-home-recent.png) |

Supplemental renderer-settling capture (direct Match World URL, outside the flow): [1366×768 Pose sample](final/1366x768/07-match-world-debug.png).

Each viewport also has a report.json. To regenerate one viewport from the worktree root, set RES129_VIEWPORT to a JSON object such as {"label":"1366x768","width":1366,"height":768}, then run node output/playwright/res-129/capture.mjs. Repeat with the other two viewport objects while the local API and production preview are running.

## Competition, team and player context

The real-data continuation adds the A-League edition tabs, Perth Glory team context, canonical player context and Season World linkage. These entity screenshots were captured from the local Vite workbench against the read-only local serving API; they use no mocks.

| Context | 1600×1000 | 1440×900 | 1366×768 |
| --- | --- | --- | --- |
| A-League teams | [10](final/1600x1000/10-a-league-teams.png) | [10](final/1440x900/10-a-league-teams.png) | [10](final/1366x768/10-a-league-teams.png) |
| A-League players | [11](final/1600x1000/11-a-league-players.png) | [11](final/1440x900/11-a-league-players.png) | [11](final/1366x768/11-a-league-players.png) |
| Season data families | [12](final/1600x1000/12-a-league-season-data.png) | [12](final/1440x900/12-a-league-season-data.png) | [12](final/1366x768/12-a-league-season-data.png) |
| Perth Glory team | [13](final/1600x1000/13-team-perth-glory.png) | [13](final/1440x900/13-team-perth-glory.png) | [13](final/1366x768/13-team-perth-glory.png) |
| Adam Bugarija, linked Match World | [14](final/1600x1000/14-player-adam-bugarija.png) | [14](final/1440x900/14-player-adam-bugarija.png) | [14](final/1366x768/14-player-adam-bugarija.png) |
| Adam Taggart, no match crosswalk | [15](final/1600x1000/15-player-adam-taggart-unlinked.png) | [15](final/1440x900/15-player-adam-taggart-unlinked.png) | [15](final/1366x768/15-player-adam-taggart-unlinked.png) |
| Season World player linkage | [16](final/1600x1000/16-season-bugarija-match-linkage.png) | [16](final/1440x900/16-season-bugarija-match-linkage.png) | [16](final/1366x768/16-season-bugarija-match-linkage.png) |

`apps/web/e2e-real/res129-entity-context.spec.ts` verifies canonical player selection in both World directions, exact URL restoration through Back/Forward, deep-link reload, no stale player values, and zero dense reads while browsing the entity and Season surfaces. The ready Brisbane–Perth match has Pose; ready Auckland–Macarthur explicitly reports Pose unavailable. Adam Taggart has no provider identity crosswalk, so his page reports no materialized player match instead of joining by name. Adam Bugarija has physical season data; the missing off-ball-run and passing rows are stated explicitly.

## RES-129 continuation: World and operational states

These captures use the final production build against the local read-only API. Rights, missing-session, and API-unavailable states were deliberately returned as 451, 404, and 503 for their respective captures. Each step asserts no horizontal document overflow. Screens 18–26 are present at all three viewports; the upstream-only session example is at 1440×900.

| State | 1366×768 | 1440×900 | 1600×1000 |
| --- | --- | --- | --- |
| Upstream-only GymAware session, no openable trials | — | [17](final/1440x900/17-gymaware-upstream-only-session.png) | — |
| Game World | [18](final/1366x768/18-game-world.png) | [18](final/1440x900/18-game-world.png) | [18](final/1600x1000/18-game-world.png) |
| Basketball spatial | [19](final/1366x768/19-basketball-spatial.png) | [19](final/1440x900/19-basketball-spatial.png) | [19](final/1600x1000/19-basketball-spatial.png) |
| Performance World, ready White CMJ session | [20](final/1366x768/20-performance-world.png) | [20](final/1440x900/20-performance-world.png) | [20](final/1600x1000/20-performance-world.png) |
| Library / evidence | [21](final/1366x768/21-library-evidence.png) | [21](final/1440x900/21-library-evidence.png) | [21](final/1600x1000/21-library-evidence.png) |
| Deterministic Prepare dialog | [22 top](final/1366x768/22-prepare.png), [scrolled readiness](final/1366x768/22-prepare-scroll.png) | [22](final/1440x900/22-prepare.png) | [22](final/1600x1000/22-prepare.png) |
| Rights restricted | [23](final/1366x768/23-rights-restricted.png) | [23](final/1440x900/23-rights-restricted.png) | [23](final/1600x1000/23-rights-restricted.png) |
| Unsupported capability | [24](final/1366x768/24-unsupported-capability.png) | [24](final/1440x900/24-unsupported-capability.png) | [24](final/1600x1000/24-unsupported-capability.png) |
| API error (404) | [25](final/1366x768/25-api-error.png) | [25](final/1440x900/25-api-error.png) | [25](final/1600x1000/25-api-error.png) |
| API unavailable (503) | [26](final/1366x768/26-api-unavailable.png) | [26](final/1440x900/26-api-unavailable.png) | [26](final/1600x1000/26-api-unavailable.png) |

The Performance World distinguishes readiness at the session level. White CMJ keeps its openable trials because its 67 sessions are ready; GymAware stays in the catalog with trial metadata visible, but its zero local streams make trials non-openable until materialization. The Data Browser skeleton exposes its loading state as a status landmark. GameLab's local title follows the active Game World label; the court retains its specific Basketball spatial title.

The real-data Back regression also enters Match World from a direct deep link with no prior catalog route and returns to the in-app catalog fallback. A separate catalog-history test verifies Back from an in-app open returns to the exact filtered edition URL. Both keep the product inside the app.

## Final acceptance evidence

- Web unit suite: 226 tests in 39 files passed; TypeScript typecheck and production build passed.
- Fixture browser suite: 105 passed, 1 real-data-only case skipped. Its direct deep-link regression opened Match World as the first route, then verified Back falls back to `/data`; the in-app path separately returned to its exact ready-filtered edition URL. Viewport overflow, axe, reduced-motion, lazy loading and renderer-smoke checks also passed.
- Real-data browser suite: the selected RES-129/123/124/accessibility/camera/performance set had 32 passing checks. One existing isolated tracking-chunk p95 assertion observed 290.6 ms against its 250 ms limit in the full run; rerunning that test alone passed and recorded 150 ms. Entity continuity, readiness-gated upstream trials, real rights states, Basketball spatial, accessibility, reduced motion, camera ownership and playback flow passed.
- Production capture: 97 API requests across the captured states, 11 dense-data requests in total, and zero dense-data requests before entering Match World. Research, Data, and Library static import closures have no renderer or ECharts chunks. Match World adds the 895 kB `View` chunk (about 235 kB gzip); the tested Research/Data/Library screens do not load the ECharts chunk.
- Build warning: the lazy ECharts chunk is 1,117 kB raw / 371 kB gzip, above Vite's 900 kB warning threshold. It was not loaded by the screens in this capture; splitting or replacing it is a separate bundle optimization decision.
- GPU receipts: [renderer benchmark](final/renderer-gpu-benchmark.json) and [hybrid field benchmark](final/hybrid-field-benchmark.json). In the repeated headless Chromium sample on AMD GCN5/D3D11, WebGL2 measured 30/34 FPS for Field, 52/53 for Pose, and 17/20 for split at 1600×1000 / 1440×900. WebGPU measured 25/47 for Field, 50/50 for Pose, and 5/4 for split; split p95 frame intervals were 333/400 ms. WebGPU performance varied by workload, including a faster 1440 Field sample, but the split result supports keeping WebGL2 as the production backend. The hybrid WebGL2 split measured 27/21 FPS; structure-lift shadow pass p95 was 0.2/0.4 ms and scalar update p95 was 1.2/1.2 ms with shadows enabled. These are headless measurements; the browser does not expose comparable allocated GPU bytes for WebGL2.
- Playback chunk p95 is variable in this headless run: one full real-browser run observed 290.6 ms against the existing 250 ms budget, while the immediate isolated retry passed at 150 ms. The saved [playback performance receipt](final/playback-performance.json) contains the passing retry. Treat the isolated chunk timing as noisy rather than as a stable pass margin.

The measured split-view frame rate and variable playback p95 remain owner-review findings. RES-129 is intentionally local and In Progress pending visual/performance review; this work does not create a PR or close the item.
