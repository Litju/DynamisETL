# Tactical metric authority

This document freezes the RES-110 vocabulary before processors or UI are implemented. The machine-readable metric definitions live in [`architecture/tactical-metrics.json`](../../../architecture/tactical-metrics.json); the source gate lives in [`sources/tactical-capability-matrix.json`](../../../sources/tactical-capability-matrix.json).

## Measurement classes

| Level | Class | Meaning |
| --- | --- | --- |
| A | `PIPELINE_DERIVED` | Deterministic geometry from canonical tracking positions. |
| B | `PIPELINE_DERIVED` | Deterministic clipped territory from canonical positions and the declared pitch boundary. |
| C | `MODEL_ESTIMATED` | A versioned kinematic arrival/influence model, not measured territory. |
| D | `PIPELINE_DERIVED` | A source event or a deterministic event/tracking join supported by source semantics. |
| E | `MODEL_ESTIMATED` | A temporal shape/phase model; not implemented until its gate passes. |

## Shared rules

- Every output carries its metric definition, algorithm/version, parameter hash, code SHA, input checksum(s), coordinate frame, measurement class, and quality evidence.
- Team geometry includes finite player and goalkeeper rows. A goalkeeper is never silently excluded. Outfield-only output requires a declared goalkeeper/outfield identity authority and a separate metric definition.
- A frame is one exact canonical `t_rel_ns` within one stream/period. Missing rows are not interpolated. Periods and data gaps are not silently crossed.
- A team calculation needs at least two included players unless the definition explicitly says otherwise. A pairwise metric needs two; a hull needs three for non-zero area.
- Frame-axis values are labelled as frame-axis values. Attack-normalized values require a declared per-team attack direction; otherwise they are unavailable.
- For model-estimated inputs, provider detection/extrapolation flags and the input measurement class remain in the result quality envelope.
- A Voronoi cell is geometric territory only. It is not a possession probability and it is not a time-to-arrival result.
- Source events and derived tactical events have separate identities. A source `Play` remains a source event; a snapshot processor must not rename it `line_break` or `pressure` without a validated definition.

## Level A: deterministic tracking geometry

For group `g` at time `t`, let `P(g,t)` be the finite included player positions in the declared frame. Centroid is the arithmetic mean. Length is `max(x)-min(x)` and width is `max(y)-min(y)`. Convex-hull area is the polygon area of `P(g,t)`'s hull. The stretch index is RMS distance to the centroid divided by the declared pitch diagonal. Pairwise metrics use each unordered pair once. Nearest-player metrics use Euclidean distance in the same frame. Rates are first finite differences over adjacent timestamps in one continuous stream.

The ball is excluded from team membership but may be used for a ball-to-centroid descriptor when a finite ball row exists. That descriptor does not identify possession.

## Level B: clipped territory

For each included player, the processor constructs the nearest-point Voronoi cell and clips it to the declared rectangular pitch. Coordinates outside the nominal rectangle are retained in the input evidence, clamped only for the bounded territory computation, and flagged. Coincident points are resolved deterministically: the lexicographically smallest object id owns the coincident cell and later ids receive zero area. Missing players simply reduce the frame's valid set and quality records the count. Team area and percentage are sums of player cells; frame-axis thirds are geometric thirds, not attacking thirds. Free space is not reported because every bounded cell is assigned by this method.

## Level C: transparent influence model

The frozen model is a bounded grid, default 53 × 35 cells, over the pitch rectangle. For player `i`, position `p_i`, velocity `v_i`, reaction time `r`, maximum speed `s`, and acceleration `a`, the arrival estimate at grid point `q` is:

```text
t_i(q) = r + solve_min_t>=0 ||q - (p_i + v_i*t)|| <= 0.5*a*t^2 + s*t
```

The implementation uses the deterministic closed-form approximation `r + distance(p_i,q) / max(s, epsilon)` when velocity is absent and a bounded forward projection plus acceleration cap when velocity is available. These assumptions are parameters, not source facts. The minimum arrival time across a team controls a grid cell; ties use stable object id. Team influence percentage is controlled-cell count divided by grid-cell count, and a selected-player influence area is controlled-cell count times cell area. A pressure-on-ball result is available only when a ball-carrier identity is explicitly resolvable; proximity to the ball alone is not possession.

## Level D: source-supported event intelligence

The accepted DFL slice supports deterministic source-event snapshots: source event id/type/subtype/team/player/context plus the nearest tracking frame on the shared provider clock. It does not support attack-normalized final-third/line-break labels in the absence of declared attacking direction, and it does not create possession or pressure from proximity. SkillCorner and Women’s/GNSS have no accepted event source in this run, so their Level D surface is unavailable.

## Level E: deferred

No Level E processor is frozen for this run. Formation, lines, block height, phase, press and transition labels need a versioned temporal model, stable-window rule, attack direction, and a capability gate that the accepted slices do not currently satisfy. UI and API return unavailable rather than labels.

## MatchLab Tactical V3 baseline

RES-113 consumes the additional role, direction, possession, functional-unit,
Delaunay, triangle, and interaction contracts in [`METHODS.md`](METHODS.md).
They do not reopen Level E: the accepted sources still lack the evidence needed
to claim formation, phase, pressing, or transition labels. Source positions
classify players; source direction is required for attack-normalized coordinates;
source possession is contextual and is never reconstructed from distance.

The V3 processor is `tactical.matchlab_shape` v1. Its detailed output fields and
fixed renderer domains live in `architecture/tactical-metrics.json`. V3 geometry
is `PIPELINE_DERIVED`; provider possession, role, direction, event, and phase
fields remain `SOURCE_DERIVED`. SkillCorner tracking remains `MODEL_ESTIMATED`
input, and its quality class is retained on every result.

## Algorithm identities

The implementation identities are reserved and versioned as follows:

- `tactical.team_geometry` v1
- `tactical.interpersonal` v1
- `tactical.spatial_territory` v1
- `tactical.arrival_time` v1
- `tactical.source_event_snapshot` v1
- `tactical.matchlab_shape` v1

They all consume canonical Arrow tables and publish dense tactical series as external Parquet. They do not read raw provider payloads or recompute in React.
