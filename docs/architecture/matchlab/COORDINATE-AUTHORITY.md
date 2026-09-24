# MatchLab coordinate authority

## Tracking and Pose sources

Tracking and Body Pose are independent SkillCorner model products. Both retain MODEL_ESTIMATED classification. Tracking uses its registered pitch-centred X/Y source coordinates and provider detection state; is_detected=false remains visible as provider extrapolation. Pose uses its source landmarks and registered hybrid frame: X/Y are pitch-global, while Z is player-centroid-relative and not registered as absolute pitch height. Provider p90 error remains an error radius, not confidence.

Their shared player ID and canonical match clock permit identity/time joins. They do not establish equal coordinates, identical sample rates or a zero residual. Never snap Pose to tracking, scale or rotate a source frame, interpolate an absent scientific sample, or remove an alignment residual.

Each view presents the latest real source frame at or before the shared playhead only while its age is no greater than 1.5 nominal sample intervals. This is a display-validity limit, not a resampling operation. A larger gap shows no current sample and reports the neighboring source times.

## Display modes

| Mode | Allowed display operation | Scientific eligibility |
| --- | --- | --- |
| Source native | Draw each source in its own declared coordinates. | Source coordinates remain eligible only through the existing processor contract. |
| Tracking-anchored display | Translate the selected Pose root/centroid to tracking XY; no rotation or scale. Show TRACKING-ANCHORED DISPLAY. | Transformed display coordinates are never processor input. |
| Display-grounded vertical | Translate selected foot/contact minimum to the rendered pitch plane and preserve relative Pose geometry. Show DISPLAY-GROUNDED · VISUAL ONLY. | Does not establish global Z, floor contact measurement or absolute height. |

When available, show tracking XY, Pose root XY, delta XY and source/model identity. Do not correct the residual away.

## Pitch geometry

Pitch3D receives positive length_m and width_m from structured metadata registered with the selected source match and tracking coordinate frame. This metadata is served with stream context. It is not inferred from extrema, user zoom, tactical raster size or a global default. If dimensions are absent or invalid, the pitch layer reports unavailable geometry and does not present a decorative field as metric authority.

X/Y observations retain the source coordinate frame. Camera movement, pitch geometry generation, display grounding and tracking anchoring are presentation operations.

## Tactical scalar fields

Processors provide the bounded grid, metric identity, method/model, units, measurement class, frame and fixed semantic color domain. The renderer only encodes those supplied values as a heatmap, contour or optional analytical elevation. Elevation is always labeled NOT PHYSICAL PITCH HEIGHT. Exact-frame tactical geometry remains exact; a sampled influence grid may show its canonical grid time and declared maximum age.

