# MatchLab Tactical V3 methods

This document freezes the RES-110 V3 baseline for functional units, shape
graphs, triangles, interactions, source possession, and directional coordinates.
It is an analysis contract, not a claim that these descriptors reproduce a
provider or FIFA model.

## Source authority

| Source | Possession | Attacking direction | Role/position | Events and phases |
| --- | --- | --- | --- | --- |
| DFL/Sportec J03WPY | `BallPossession` is team-level: 1=home, 2=away; `BallStatus` is 0=inactive, 1=active. It does not name the possessing player. | Not declared. Home/away and period alone do not establish which goal a team attacks. | Match-information `PlayingPosition`; apply the exact code map in `tactical-capability-matrix.json`; absent/unmapped codes remain `unknown`. | Accepted synchronized source event stream is retained as `SOURCE_DERIVED`. Kick-off/final-whistle labels delimit periods; they are not phase labels. |
| SkillCorner Open Data 1925299 | Each accepted tracking frame may declare `possession.group` and `possession.player_id`; null/missing means unknown, not no possession. | Accepted `home_team_side` has one direction per half. Home uses that value; away uses its inverse. | Match `player_role.position_group`, `name`, and `acronym`; `GK` acronym is goalkeeper authority even when the broad group is `Other`. | Dynamic-event and phase files are listed upstream but absent from the accepted local manifest. They are unavailable in this run. |

### Possession contract

Possession is a source-declared frame context, not inferred from ball proximity.
DFL values map to the match-information home/away team IDs. SkillCorner values
map `home team`/`away team` to metadata team IDs and retain `player_id` when
present. DFL active/inactive ball status is kept separately. Unknown values,
missing frames, and absent player identity remain null. Possession outputs carry
`SOURCE_DERIVED`; tactical geometry conditioned on them remains
`PIPELINE_DERIVED` and carries the original possession fields and class.

### Direction and normalized frame contract

Raw provider X/Y is never overwritten. When a declared team direction exists,
the team-relative normalized view rotates both axes 180 degrees only for
`right_to_left` (`x'=-x`, `y'=-y`); `left_to_right` is unchanged. This makes the
analysed team's attack point along +X while preserving distances and handedness.
The transform is selected independently for each team and period. A comparison
between teams uses one focal team's transform for both teams in that comparison.
No transform is applied when direction is absent; such results are explicitly
frame-axis results. Normalized third/zone labels are unavailable without source
direction.

## Functional units

Source roster roles are fixed for a player identity during the accepted match;
they are not updated from instantaneous coordinates. `GK`, `DEF`, `MID`, `ATT`,
and `unknown` are reported separately. For a unit with at least one positioned
player, centroid is the coordinate mean, line height is mean normalized X when
direction exists (otherwise mean source-frame X), depth is X range, width is Y
range, and dispersion is the root-mean-square Euclidean distance to the
centroid. Orientation is the undirected principal covariance axis in degrees
`[0,180)`; it is null for a singleton or isotropic point cloud. GK geometry is
valid for one player; orientation still remains null.

DEF↔MID and MID↔ATT gaps are absolute differences between unit line heights.
They describe frame-axis separation and do not assert line order. Outfield block
depth is the X range across source-labelled DEF/MID/ATT players; goalkeeper and
unknown-role rows are excluded. Each result reports role counts, direction
availability, and source-frame versus team-normalized coordinates.

## Delaunay graph and triangles

Raw research geometry is the two-dimensional Delaunay triangulation of finite
player positions per team and exact timestamp. Coincident points are represented
by the lexicographically smallest player ID; fewer than three unique
non-collinear points produce no triangles. Player IDs and output rows are sorted
to make identical-input runs stable. Raw geometry remains available for
research/debug and is not treated as a team success score.

The default live shape graph is the subset of current raw Delaunay edges present
in at least 80% of observed team-frame timestamps in the trailing 1.0 s. Frames
with too few or collinear points count in the denominator with an empty graph.
A stable edge also requires at least 0.8 s of observed window coverage. A time
gap over 0.2 s starts a new persistence window. Selected-player neighbourhood is
the set of stable incident edges; it makes no marking or tactical-intent claim.

Each valid raw triangle reports area, longest/shortest edge ratio, undirected
principal orientation, centroid-to-ball distance when available, zone and zone
frame, triangle-ID persistence, opposing players inside, and geometric nearest
team at its centroid. Nearest-team context is the deterministic Voronoi owner at
that point. Its distance margin is nearest-opponent distance minus nearest-
focal-team distance: positive favors the focal team, negative favors the
opponent, and zero is an equal-distance tie. It is not a probability or
possession label. Triangle persistence divides occurrences by all observed
team-frame timestamps in the same trailing window. Source possession
team/player/status is included as separate context only.

Every derived row carries `quality_json` with input measurement classes, role
counts, direction availability, missing/out-of-pitch/extrapolated/duplicate
counts, and whether source possession context was present and known.

With direction, zone thirds use normalized X boundaries at `-L/6` and `+L/6`:
`own_third` for `x < -L/6`, `middle_third` for `-L/6 <= x < L/6`, and
`opponent_third` for `x >= L/6`. Without direction, only `left_third`,
`center_third`, or `right_third` frame zones may be emitted. Points outside the nominal pitch are
labelled `out_of_bounds`; no clipping is used for triangle geometry.

## Attacker/defender geometry

These descriptors require source-classified ATT and DEF roles. For each
attacker, nearest defender is the Euclidean minimum with player ID as the tie
break. The second-nearest defender is reported as a geometric cover candidate,
not a cover assignment. Local overload counts ATT and DEF players within a
versioned 10 m radius centered on the attacker; the signed margin is ATT minus
DEF. A defender is geometrically tied only when the attacker and defender are
mutual nearest opponents. A free attacker has no mutual-nearest defender. These
are spatial constructs, not marking assignments.

## Scalar-field domains

The machine-readable domains in `architecture/tactical-metrics.json` are the
RES-113 rendering authority. Numeric values are retained without clipping;
display scales may saturate at their declared bounds. Voronoi territory is
geometric area/fraction. Dominant region is a winner-take-all arrival-time
surface, not a probability. Pressure is an arrival-time model output and is
unavailable without an explicit carrier. Provider phase/event labels remain
`SOURCE_DERIVED`; any DynamisData classifier must have a separate version,
class, and output field.
