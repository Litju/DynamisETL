# Data grain

`DataGrainKind` version 1 is scientific metadata. The canonical axes are frozen in [`system-v4.json`](../../../architecture/system-v4.json). Each declared axis participates in row identity; all axes must exist and be non-null, and duplicate keys are rejected before artifact publication.

| Kind | Logical row key |
| --- | --- |
| FRAME_SERIES | contest, period, canonical_time, entity |
| JOINT_FRAME_SERIES | contest, period, canonical_time, subject, joint |
| EVENT_SERIES / PLAY_BY_PLAY | contest, period, sequence_index |
| GAME_SUMMARY | contest |
| PLAYER_GAME | subject, contest |
| TEAM_GAME | team, contest |
| PLAYER_SEASON | subject, team, competition_edition |
| TEAM_SEASON | team, competition_edition |
| TRIAL_SERIES | subject, trial, sample_index |
| SENSOR_SERIES | subject, stream, canonical_time |

Dataset and artifact identity are enclosing scope, not substitutes for these axes. Joint-valued trial rows append `joint` to `TRIAL_SERIES`; this represents SPL free-throw pose without pretending that a training session is a contest. A provider table name or UI grouping never changes the grain. Unknown legacy artifacts may remain unannotated during additive migration; new V4 products must declare and validate their grain.
