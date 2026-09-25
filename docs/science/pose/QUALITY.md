# Pose analysis quality

Quality evidence is shown beside each selected metric and independently for
each side of a bilateral comparison. Three authorities remain separate:

1. **Provider evidence:** landmark row presence, availability, source/model
   measurement class, and the provider p90 predicted error radius.
2. **Pipeline evidence:** finite-coordinate checks, selected-metric coverage,
   dropout intervals, contiguous-segment identity, and derivative eligibility.
3. **Biomechanical-model evidence:** fit residual and supported degrees of
   freedom, only if a later Layer C model gate passes.

The provider error radius must not be reused as a pipeline confidence score.
Missing or unavailable observations remain explicit gaps and do not become
zero-valued samples.

For a selected range, quality summaries report the exact subject, stream,
canonical from/to times, expected cadence, observed/usable-frame fraction,
landmark-specific availability, dropout count and intervals, longest dropout,
and mean/median/p95 of available provider error-radius samples. Label an error
summary with the provider's p90-radius semantics. A selected derivative also
reports its sampling rate, temporal segmentation threshold, filter and
parameters, differentiation scheme, edge policy, minimum usable segment
length, and whether the current sample is eligible.

Never aggregate these distinct measurements into an undocumented scalar
quality score. A missing model, source dropout, insufficient landmarks, invalid
coordinates, rights restriction, and transport failure remain distinct states.
