# ADR-006: Playhead-driven continuous playback and Pose camera authority

_RES-109 §11 manual-acceptance amendment; contract version 2.0.1._

---

## Context

The first V2 chunk implementation planned active windows from durable
`committedTimeNs`, while the wall-clock playback loop advanced transient
`playheadNs`. Adjacent chunks were prefetched but never became active, producing
the observed approximately 16-second exact-Pose cutoff. Pose also combined
source coordinates, display recentering, trajectory bounds, and camera control
into one implicit authority.

## Decision

- `PlaybackChunkCoordinator` is the shared browser boundary authority for
  continuous dense Signal, Field, and Pose replay.
- The live `playheadNs` selects the canonical non-overlapping active chunk;
  previous and next chunks are prefetched and bounded in cache.
- A missing required exact chunk enters explicit `BUFFERING`, clamps the clock
  at the current chunk boundary, and resumes automatically after readiness.
  Canonical minimum/maximum bounds stop playback explicitly.
- Pose uses two display-only coordinate authorities: `body_local` for a
  single-subject analytical view, rooted deterministically from current
  landmarks, and `match_world` for source XY placement and all-subject context.
  Neither display transform changes source data or scientific metrics.
- Pose camera ownership is explicit: `body_local`, `follow_subject`,
  `joint_focus`, `world_fixed`, `all_subjects`, and `manual`. Automatic target
  damping is presentation-only; manual controls are never overwritten by an
  automatic controller.
- Landmark instances, provider/display/analytical line layers, angle geometry,
  error radii, selection state, and telemetry read the same current-frame
  authority at playback cadence.

## Evidence

- `PlaybackChunkCoordinator` unit matrix covers three forward boundaries,
  reverse buffering, seek re-plan, reverse departure from the canonical
  maximum, and bounded previous/active/next retention.
- Local Chromium acceptance covers Pose and Field multi-boundary forward
  playback, reverse playback, exact boundary continuity, delayed-chunk
  `BUFFERING`, seek, entity scope, and camera-mode controls.
- Pose model checks cover deterministic body roots, dropout fallback, and
  travel-invariant body-local bounds.

## Consequences

The URL and committed state remain low-frequency durable context. Query state
changes only on canonical chunk handoff or context change; frame cadence stays
in Zustand/imperative renderer refs. An unready exact boundary pauses the wall
clock visibly instead of freezing a stale renderer or silently skipping data.

