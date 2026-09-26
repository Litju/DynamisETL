# Product routing contract

Routing is a pure, deterministic function of locally available capability evidence and declared data grains.

| Product | Required local evidence | Optional evidence |
| --- | --- | --- |
| MatchLab | TRACKING plus FRAME_SERIES | BALL_TRACKING, POSE, EVENTS, PHASES, TACTICAL |
| GameLab | PLAY_BY_PLAY or EVENTS plus PLAY_BY_PLAY or EVENT_SERIES | BOX_SCORE, LINEUP |
| SeasonLab | SEASON_AGGREGATE plus PLAYER_SEASON or TEAM_SEASON | — |
| PerformanceLab | FORCE, IMU, LPT or GNSS plus TRIAL_SERIES or SENSOR_SERIES | — |

Routes do not depend on provider name. Upstream-only capability does not open a local product. MatchLab remains the existing continuous spatial analysis surface; GameLab, SeasonLab and navigation experiences are routing targets only in RES-119, not new product implementations.
