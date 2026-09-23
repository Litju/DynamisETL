# MatchLab Tactical V3 validation

## Synthetic known answers

The processor tests use analytic coordinates and explicit source-context maps.
They cover:

- one-player goalkeeper and symmetric DEF/MID/ATT centroids, line heights,
  widths/depths, covariance orientation/dispersion, inter-line gaps, and block
  depth;
- direction normalization for both sides while preserving pair distances and
  raw source coordinates;
- square Delaunay triangulation, deterministic cocircular output, duplicate
  positions, collinear points, stable-edge persistence over all observed team
  frames, and a time-gap reset;
- triangle area/aspect/orientation, ball distance, zone, opponent inclusion,
  nearest-team context, and persistence bounds;
- nearest/second-nearest defender, 10 m overload, mutual-nearest tie-up, and
  free-attacker rules;
- missing roles, possession, ball, and direction failing closed without
  synthesized labels; source possession remains `SOURCE_DERIVED`.

## Accepted local source checks

The bounded DFL and SkillCorner acceptance receipts record the accepted raw
metadata/tracking checksums, canonical tracking input checksum, role and
direction availability, possession coverage, row counts, output checksums, and
identical rerun checksums. Only receipts and aggregate counts are stored outside
the repository; source rows are not committed.

DFL possession is checked against the home/away match-information IDs and its
active/inactive status. SkillCorner possession group/player is checked against
match metadata. Normalized direction is checked for each team and half when the
source field is valid. The tests do not claim that roster positions equal
time-varying tactical positions or that source possession is event-ground truth.

## Regression gates

Run the targeted tactical authority/geometry/shape tests, the full Python suite,
Python format/lint/type checks, web type/lint/unit/API/build checks, repository
and rights guards, RES-112 browser acceptance, and the real-browser RES-110 and
RES-112 acceptance paths. A deterministic receipt requires both its run identity
and every materialized Parquet checksum to match on rerun.
