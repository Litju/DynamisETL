# Pose analytics contract

## Scope and authority

RES-111 adds geometric and derivative Pose analytics to MatchLab. The canonical
Pose source remains authoritative for provider landmarks, source timestamps,
subject identity, availability, coordinate-frame metadata, measurement class,
and provider error-radius evidence. Analytical results are pipeline-derived and
retain source and processor provenance. MatchLab's player/time context, Arrow
worker path, playback coordinator, Pose viewport, and Analysis Dashboard remain
the integration authorities; this work does not create a parallel application
state or rendering stack.

Pose frame preparation is already performed by the shared Arrow/Comlink worker
(`preparePoseWindow`): it groups exact timestamps by subject, applies the
registered skeleton order, and packs positions, row presence, availability,
provider error radius, and observed-frame state into transferable typed arrays.
The viewer materializes only the active bounded window for display. Analytical
science stays in versioned Python processors and is never calculated from
React state, a rendered frame, or a reduced plot sample.

## Metric layers

| Layer | Meaning | Measurement class | RES-111 boundary |
| --- | --- | --- | --- |
| 0 | Provider landmark coordinates, presence/availability, source frame, identity, and provider p90 predicted error radius | Provider source class | Preserve exactly; p90 radius is not a probability, confidence interval, or pipeline quality score. |
| A | Relative landmark displacement, segment vectors/length/orientation descriptors, explicitly named three-landmark included angles, and geometric ROM | `PIPELINE_DERIVED` | Name the landmarks and coordinate frame. Never call an included angle anatomical flexion by implication. |
| B | Temporal landmark/angular derivatives on valid contiguous observations | `PIPELINE_DERIVED` | Version sampling, segmentation, gap, filter, differentiation, edge, and minimum-length policies. No hidden interpolation or cross-gap derivative. |
| C | Joint-coordinate-system / anatomical joint kinematics from an explicit biomechanical model | `MODEL_ESTIMATED` | Unavailable until the committed sufficiency matrix and model experiment pass the stated gate. |
| D | Range, extrema, bilateral, and waveform summaries derived from accepted A/B/C series | `PIPELINE_DERIVED` | Keep both-side quality and coverage separate; no diagnosis, risk, or normative label. |

## Existing processor and additions

The existing `pose.translation_invariant_kinematics` processor (v1.0.0) is the
initial Layer A/B authority. It produces processor-defined segment lengths,
explicit three-point angles, angle ROM, angular velocity, per-landmark
availability, and mean provider error radius. It splits observed frames into
contiguous segments and restarts derivative/filter state at gaps. Its series
retains canonical time and segment identity.

RES-111 extends this foundation with per-landmark / segment kinematics,
gap-safe landmark derivatives, first-class quality summaries, and bilateral
descriptors. Dense series remain external Parquet; Gold serves bounded scalar
and range summaries. Layer C is a separate experiment and will not be inferred
from the existence of 29 landmarks.

The accepted SkillCorner run currently precomputes six lower-limb landmarks
relative to the observed `midHip` anchor. The processor contract accepts any
registered landmark selection; raw source coordinates for the complete
29-landmark set remain separately accessible.

The machine-readable definitions are in
[`metric-definitions.json`](metric-definitions.json); the source/model gate is
in [`skillcorner-capability-matrix.json`](skillcorner-capability-matrix.json).

## Required provenance

Every analytical sample or summary preserves subject, session, period/trial,
exact canonical time or range, source stream and checksum, source coordinate
frame, measurement class, algorithm/version, full parameters, code SHA, and
temporal segment/gap identity. Provider p90 error radius, pipeline checks, and
model residuals are separate evidence classes and must not be collapsed into
one opaque score.
