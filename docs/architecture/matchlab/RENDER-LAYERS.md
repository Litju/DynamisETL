# MatchLab render layers

All layers use the same MatchFrameContext and one R3F Canvas. A layer may be hidden without changing its source data, scientific values or availability.

| Layer | Responsibility | Source and limits |
| --- | --- | --- |
| PitchLayer | Source-sized metric turf, markings, goals and rendered pitch plane. | Structured registered source dimensions; never inferred from player extents. |
| TrackingLayer | Player/goalkeeper/ball instances, provider detection state, trails and picking. | Exact tracking rows; preserve MODEL_ESTIMATED and extrapolation disclosure. |
| TacticalLayer | Team/unit geometry, graphs, territory, scalar surfaces, events and paths. | Processor outputs only; preserve each metric’s method, time, fixed domain, measurement class and availability. |
| PoseLayer | Provider landmarks and display topology, declared analytical segments/angles, error radii and joint picking. | Exact Pose observations and provider topology; no invented links, joints or metrics. |
| ContextLayer | Labels, selection identity, trails, source alignment residuals and mode badges. | Presentation context; transforms never enter scientific processors. |

Tracking and Pose retain separate frame identities, timestamps, coordinate frames and quality. Layer visibility does not imply that the underlying source or tactical capability exists.

## Shared primitives

- Use InstancedMesh for repeated players and landmark markers.
- Use dynamic or batched BufferGeometry for trails, polygons, contours and segments.
- Use typed GPU textures or buffers for processor-produced scalar grids.
- Use source-sized procedural geometry for pitch markings.
- Keep renderer selection IDs available to DOM summaries so labels, position or color are never the only selection signal.

