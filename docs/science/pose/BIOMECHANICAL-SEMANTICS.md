# Pose biomechanical semantics

## Source frame and measurement class

SkillCorner Body Pose provides 29 model-estimated landmarks at 25 Hz. X/Y are
pitch-global metres; Z is relative to the player's centroid and is not
registered as pitch height. Pose and tracking are generated separately, so
their X/Y observations may be slightly misaligned. Preserve both streams and
their alignment evidence without overwriting one with the other.

The source `p90_mae_cm` is a provider-predicted 90th-percentile error radius
relative to the player's pose. Report it as provider error-radius evidence. Do
not call it a probability, confidence, confidence interval, or measurement
uncertainty. `MODEL_ESTIMATED` remains the source measurement class; deterministic
derived geometry is `PIPELINE_DERIVED`.

## Geometric names

A geometric included angle is defined by three named landmarks: the angle at a
vertex between two vertex-to-endpoint vectors. For example,
`left_knee_included_angle` is computed from `lHip`, `lKnee`, and `lAnkle`. It is
not named knee flexion. A segment is a named relative vector between two
landmarks. Report its length or explicitly declared source/viewer-frame
descriptor; do not imply a bone axis, anatomical local coordinate system, or
absolute vertical reference.

Body-relative values must name their anchor and use the same observed frame.
They are not whole-body center of mass. Missing required landmarks produce an
unavailable sample; they are never replaced by a nearby joint, interpolation,
or a display estimate.

## Anatomical/model-estimated gate

Standardized anatomical joint coordinates require defined local coordinate
systems for the articulating segments, a landmark-to-model mapping, and an
identifiable joint coordinate system. The SkillCorner 29-landmark set is a
landmark set with display connections, not an anatomical parent graph. It lacks
the bony landmarks and subject-specific calibration needed to identify
defensible segment frames and several joint degrees of freedom. Its hybrid
coordinate registration and predicted keypoints add further model residual and
validation requirements.

The current sufficiency decision is therefore **fail closed for Layer C**:
ship geometric Layer A and eligible derivative Layer B only. Do not run or
publish inverse kinematics, standardized joint angles, inverse dynamics,
moments, forces, muscle variables, injury risk, or technique-quality labels
from SkillCorner Pose alone. Re-open this decision only with an explicit
biomechanical model, mapping/scaling/frame contract, residual and per-joint
quality evidence, supported-DOF matrix, and independent validation receipts.

The candidate-by-candidate capability decision is machine-readable in
[`skillcorner-capability-matrix.json`](skillcorner-capability-matrix.json).

## Reporting language

Use distinct labels for:

- source/model-estimated Pose observation;
- geometric included angle or segment descriptor;
- versioned derivative estimate;
- pipeline quality and coverage;
- provider p90 predicted error radius;
- model-estimated anatomical quantity, only if the Layer C gate later passes.

Do not use normal/abnormal, risk, diagnostic, or performance-quality language
without a separately defined and validated model.

## Research and source basis

- [SkillCorner Body Pose guide](https://skillcorner.github.io/opendata/notebooks/tutorials/05_Body_Pose/Part1_Getting_Started_with_Body_Pose/) documents the 29 keypoints, 25 Hz cadence, coverage gaps, provider p90 error radius, and centroid-relative Z limitation.
- [ISB ankle, hip, and spine joint-coordinate-system recommendations](https://pubmed.ncbi.nlm.nih.gov/11934426/) define local articulating-bone axes as the basis for standardized joint reporting.
- [ISB upper-limb joint-coordinate-system recommendations](https://pubmed.ncbi.nlm.nih.gov/15844264/) provide the corresponding shoulder, elbow, wrist, and hand definitions.
- [ISB 2024 kinematics definition and reporting recommendations](https://pubmed.ncbi.nlm.nih.gov/39032224/) emphasize explicit model definition, calibration, analysis, and quality assessment.
- [Pose2Sim robustness workflow](https://pmc.ncbi.nlm.nih.gov/articles/PMC8512754/) and its [accuracy evaluation](https://pmc.ncbi.nlm.nih.gov/articles/PMC9002957/) describe calibrated, synchronized multi-camera observations and constrained OpenSim fitting; those inputs and validation are not provided by the current SkillCorner landmark stream alone.

These sources set the modeling/reporting boundary. They do not validate
DynamisData-derived metrics; each implemented processor still requires its own
known-answer, gap, quality, and real-data validation receipts.
