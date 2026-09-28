# Product routing contract

Routing is a pure, deterministic function of locally materialized capability evidence and declared data grains. `/api/catalog/read-model` projects canonical contests, competition editions and human-performance sessions into one metadata-only browser contract. It does not acquire source files or read Parquet/Arrow payloads.

| Product | Required local evidence | Optional evidence |
| --- | --- | --- |
| MatchLab | TRACKING plus FRAME_SERIES | BALL_TRACKING, POSE, EVENTS, PHASES, TACTICAL |
| GameLab | PLAY_BY_PLAY or EVENTS plus PLAY_BY_PLAY or EVENT_SERIES | BOX_SCORE, LINEUP |
| SeasonLab | SEASON_AGGREGATE plus PLAYER_SEASON or TEAM_SEASON | — |
| PerformanceLab | FORCE, IMU, LPT or GNSS plus TRIAL_SERIES or SENSOR_SERIES | — |

Routes do not depend on provider name. Upstream-only capability does not open a local product. SkillCorner football and basketball contests resolve through `SessionSportContext` and provider identity crosswalks; SportsDataverse season assets use the committed release metadata snapshot and the adapter's canonical competition-edition IDs. Human-performance sessions retain their dataset-scoped session identity. Display names never merge entities.

Each catalog resource reports upstream, registered, materialized and ready states separately, plus an eligible next preparation stage when one exists. The browser treats provider/source as provenance and a filter. It links only routes whose local capabilities and grain pass the table above, with the basketball spatial view gated by materialized tracking plus `FRAME_SERIES`.
