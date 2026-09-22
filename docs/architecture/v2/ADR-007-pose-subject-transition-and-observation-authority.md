# ADR-007: Atomic Pose subject transitions and observation authority

_RES-109 §12 manual-acceptance amendment; contract version 2.0.2._

---

## Context

V2.0.1 treated a subject change as separate URL, Zustand, and query updates.
After playback had advanced, that allowed a new subject to inherit an old
canonical time and render an empty scene while telemetry mislabeled missing
rows as unavailable landmarks. Literal `t_ns=0` is not valid for sparse Pose.

## Decision

- The serving API exposes stable Pose `entity_observations` for each artifact
  entity: first observed canonical time, last observed canonical time, and
  observed-frame count. A bounded observations route resolves an exact first
  frame inside an explicit durable range when the artifact-level bounds are not
  sufficient.
- Subject selection stops playback, clears subject/joint/hover transient state,
  retires only the previous subject's query scope, resolves an exact target,
  and navigates subject plus `t_ns` in one durable transaction.
- The replacement coordinator is anchored to that same target. A switching
  state suppresses both Pose rendering and telemetry until the exact query is
  ready; its requests carry coordinator ownership metadata.
- An observed frame reports provider availability (`N observed · M unavailable`).
  A missing current subject frame reports temporary absence, and an entity with
  no observations in the active period/range reports no Pose. Neither state
  fabricates unavailable landmark rows.
- In all-subject mode, subject selection changes identity focus while the
  global exact query remains unscoped by entity.

## Evidence

- `EntityObservationView` serving and bounded-range tests reject unavailable
  rows and preserve numeric entity IDs.
- Pose unit tests cover first-observation targets, no-overlap ranges, atomic
  target-time selection, numeric identities, and switching state cleanup.
- The §12 browser matrix covers paused/playing/BUFFERING switches, first
  observation after zero, temporary absence, no Pose, all-subject focus,
  reload, back/forward, and replacement-subject request survival.

## Consequences

Subject identity and canonical time no longer drift independently. The URL
remains the durable authority, while the transient store provides a visible
switching gate and renderer/telemetry synchronization. Sparse Pose remains
honest: roster membership is not treated as observation availability.
