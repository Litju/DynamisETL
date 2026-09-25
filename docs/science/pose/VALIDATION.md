# Pose analytics validation plan

## Geometric known-answer checks

- Straight and right-angle three-landmark configurations.
- Known segment length, translation invariance, and rigid-rotation invariance
  for distance/angle quantities where mathematically expected.
- Symmetric left/right trajectories with a known difference and timing offset.
- Missing, unavailable, duplicate, and non-finite landmark rows fail closed.
- Provider error-radius evidence remains distinct from derived values.

## Derivative checks

- Constant position gives zero velocity; linear position gives constant
  velocity; a quadratic trajectory gives its known acceleration when eligible.
- A sinusoidal angle gives its analytical angular derivative within the
  declared numerical tolerance.
- Explicit gaps reset derivative/filter state; no bridge or hidden interpolation
  is allowed. Unavailable joints remain gaps, not zero.
- Sensitivity is reported at the source cadence (SkillCorner Body Pose: 25 Hz)
  and across accepted filter choices. Acceleration fails closed unless its
  minimum-segment and quality gates pass.

## Quality and real-data checks

- Synthetic dropout and provider error-radius patterns have exact expected
  coverage, interval, and distribution summaries.
- Accepted local SkillCorner data is checked across multiple subjects and time
  ranges, including dropout and high/low provider error-radius samples.
- Do not commit restricted raw rows. Keep data-dependent receipts outside the
  repository according to the existing evidence policy.

## Layer C checks

Layer C is unavailable under the current SkillCorner-only sufficiency decision.
If the gate is reopened, the separate experiment must validate model-generated
known trajectories, landmark-to-model mapping, scaling and frame transforms,
per-DOF reconstruction error, perturbation sensitivity, missing-marker failure
cases, and independent reference motion capture before production use.

## Browser and performance checks

Use exact served processor series, bounded chunks, and the RES-109 playback
coordinator. Verify subject/time synchronization, selected-range interaction,
quality display, keyboard access, semantic raw-landmark inspection, and reduced
motion. Benchmark one subject, all subjects, selected-metric waveform, quality
dashboard, and all analysis layers without allowing analysis updates to rebuild
the 3D scene.
