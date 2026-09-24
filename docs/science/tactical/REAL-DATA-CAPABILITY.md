# RES-110 real-data semantic gate

This is the evidence-first gate for tactical implementation. It records the accepted local artifacts and the source semantics that are safe to expose. Raw source rows remain outside Git.

## DFL/Sportec IDSSE

Accepted slice: match `DFL-MAT-J03WPY`, pinned source revision `a715a38dfbaf5f58e431727c2b78d174101a703c`.

The local discovery receipt reports 146,211 distinct 25 Hz tracking frames, 23 entities per frame, 53 observed player object identities across periods, a 105 m × 68 m pitch, and 3,362,853 entity observations. Match information supplies two team ids, roster/player identity and playing-position fields. The canonical tracking rows are `RAW_MEASURED`; the canonical event rows are `SOURCE_DERIVED`.

The event export has 1,504 source rows, including 60 `Delete` retractions; 1,444 rows are canonicalized after explicit retraction exclusion. It contains provider types such as `Play`/`Pass`, `ShotAtGoal`, `TacklingGame`, `BallClaiming`, `CornerKick`, `FreeKick`, `ThrowIn`, and `Substitution`, with provider team/player/context attributes. The source event order is not chronological; the adapter sorts by `(EventTime, EventId)`. Tracking and events share the provider UTC clock and the event coordinates are transformed from the provider bottom-left frame into the declared pitch-centred frame.

The accepted tracking artifact carries team possession (`BallPossession=1` home, `2` away) and ball activity (`BallStatus=0` inactive, `1` active); this is team-level and has no carrier player id. The accepted roster carries source `PlayingPosition` codes, with absent/unmapped codes left unknown. The provider does not declare which direction on the pitch X axis is toward either goal, so no attack-normalized thirds, line breaks, or receptions behind a line are emitted. Kick-off/final-whistle event labels delimit periods; they are not provider phase labels. The provider tracking attributes `D`, `A`, and `M` remain undecoded Bronze evidence.

Safe scope: Levels A and B; Level C arrival/influence estimates without an attack-direction claim; Level D source-event snapshots joined by the shared source clock; V3 functional units from mapped roster roles; and raw/stable shape geometry with frame-axis zones. Source possession is exposed as team context only. Pressure-on-ball and attack-normalized phase/event metrics remain unavailable. Level E is unavailable in this slice.

## SkillCorner Open Data

Accepted slice: match `1925299`, tracking revision `4340d274572876239c154c90bc507a9b3250a656`, body-pose revision `a62e1ec1e3b82952042a7f7fa9dafd77c0e0822a`.

The accepted artifact has two teams from match metadata, 36 declared players and 32 observed tracking player ids, 10 Hz tracking and a ball when coordinates are present. Tracking is a broadcast computer-vision/model product (`MODEL_ESTIMATED`), with `is_detected=false` meaning provider extrapolation. The accepted match metadata provides role group/name/acronym; `GK` acronym is used for goalkeeper identity even when the broad position group is `Other`. Tracking frames provide a source possession group and optional player id. Match metadata `home_team_side` declares each half's direction; the away direction is its inverse. Raw X/Y remains authoritative and preserved, with team-relative normalized coordinates derived by the frozen 180-degree transform.

The local accepted slice contains no dynamic-event or phase artifact. The capability matrix therefore does not enable Level D or provider phase/event outputs. The tracking product is sufficient for A/B, a partial C surface, V3 role geometry, shape graphs, triangles, source possession context, and direction-normalized coordinates, with the input quality and model-estimated class disclosed on every result. No DynamisData phase classifier is enabled by this source metadata.

## Women’s Soccer Positioning / GNSS

Accepted slice: workbook `J01.xlsx`, version `1.0`.

The discovery receipt reports 19 athlete sheets and 858,542 rows at a nominal 10 Hz. Each sheet contains `local_time`, latitude, longitude, `speed(km/h)`, and an all-null `hr(bpm)` column. Sheet names are the provider athlete identities. Timestamps are local wall-clock text with no timezone or UTC authority. The provider does not declare a geodetic datum; WGS 84 is an explicit pipeline interpretation with no coordinate transformation.

This is not full opposition tracking. It has no team grouping, opposition, ball, event, pitch coordinate frame, attacking direction, possession, or phase authority. The tactical matrix therefore disables team geometry, territory, influence, event-linked intelligence, and shape/phase models. Existing GNSS locomotor exploration remains valid and outside the tactical metric family.

## Capability rule

Dataset names never turn a surface on. A capability is enabled only when the accepted artifact has the required identity, coordinate, clock, event, and quality semantics. Unavailable capabilities are returned explicitly and are not replaced with zeros, inferred possession, invented pressure, or labels derived from a visualization.

The committed machine-readable matrix is [`sources/tactical-capability-matrix.json`](../../../sources/tactical-capability-matrix.json). The local discovery receipts and artifact checksums are the evidence trail; no raw rows are committed.
