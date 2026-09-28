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

Production JavaScript loaded before Match World: 42 assets, 1,164,541 raw bytes (374,414 gzip-equivalent bytes). Match World adds 18 assets, 1,368,200 raw bytes (368,436 gzip-equivalent bytes); the largest is View-YjPNc8A4.js at 895,184 bytes (235,152 gzip-equivalent). The separate ECharts chunk is not requested by this slice. Per-viewport reports include each route's loaded chunks and API paths.

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
