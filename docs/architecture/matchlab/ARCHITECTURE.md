# MatchLab V3 architecture

Status: frozen for the MatchLab rendering boundary. Current contract: architecture/system-v3.json, version 3.1.0 (RES-113 §§21–22 hybrid Field amendment).

## Scope

V3 owns the Field/Pose renderer boundary, the renderer-facing MatchFrameContext, frame preparation, pitch/scalar rendering and shared Canvas. RES-109 remains the system authority for storage, scientific processing, provenance, rights, playback and measurement classes. RES-110 remains the authority for tactical methods and capability claims. RES-111 remains the authority for Pose science. RES-114 owns final workspace composition and proportions.

No renderer, shader or browser worker becomes a scientific processor. Tracking and Pose continue to use their separately generated source artifacts, methods, identities, clocks and measurement classes.

## Runtime flow

The router restores dataset, session/match, period, canonical time, selected participant and MatchLab mode. TanStack Query loads bounded registered artifacts and tactical processor output. The existing Arrow/Comlink worker prepares source-specific typed frames. MatchFrameContext combines those authorities into one renderer snapshot. One R3F Canvas draws independently toggleable layers and Drei Viewports; Three buffers change at frame cadence.

Router durable context, Query artifacts/data, Zustand playhead/hover, and Arrow worker buffers converge on MatchFrameContext. One R3F Canvas renders Pitch/Tracking, Tactical/scalar, Pose and Context/picking layers.

The context is an API over the existing state owners. It is not another store. Player and time changes have one transaction path, while frame cadence remains out of React reconciliation.

## Locked decisions

- Three.js, React Three Fiber and Drei; one Canvas and one WebGL renderer.
- WebGL2 is the initial production backend. WebGPU is considered only after the final representative scene is complete and measured.
- The registered source match dimensions determine the procedural pitch. Missing geometry is an explicit unavailable state.
- Field defaults to Tactical Map with a fitted OrthographicCamera and stable margins around the registered source pitch. Structure Lift uses an oblique orthographic camera; optional Perspective Explore is not the tactical default. Reset returns the selected preset to deterministic framing, and camera movement never alters source coordinates.
- The procedural pitch is source-sized and includes a visible turf edge and three-dimensional goal frames/nets. Tracking uses grounded planar point markers; source identity is carried by labels and selection state, not glyph height.
- Default tactical structure comes from V3 source-roster GK/DEF/MID/ATT functional-unit rows, with centroids and inter-line gaps. Level A convex hull is optional occupied-area context. Stable graph edges, selected-player triangles and selected ATT-to-nearest-DEF relations are requested and drawn only in their Relations mode.
- Tracking positions, functional-unit structure, inter-line gaps, graph edges, local triangles, opposition relations, hull/Voronoi geometry, contours and events preserve their scientific pitch-plane XY. Presentation-only layer offsets live in `render-layer-depths.ts` and remain visually subtle.
- `ScalarFieldLayer` is the only analytical 2.5D surface. A metric-specific `ElevationSpec` declares its scientific domain, units, display transform, height limit, pitch-plane baseline and fixed color domain. Heights update the mesh from worker-prepared typed buffers; no scientific metric is recalculated in React or a shader. Its label is `ANALYTICAL ELEVATION · NOT PHYSICAL HEIGHT`.
- Tactical Map disables shadows. Structure Lift enables exactly one restrained DirectionalLight shadow map; the pitch receives the analytical surface's shadow and planar tactical layers do not cast meaningful shadows. Split mode keeps Field orthographic and Pose genuinely 3D.
- Tactical views are ordered Live / Structure / Relations / Space / Events / Range / Report. Selecting a player or relation resolves through MatchFrameContext and stays synchronized between Field and Pose.
- Tracking/Pose frames resolve independently against one signed BigInt canonical time. A source frame is the latest real sample at or before the playhead within the declared source-rate tolerance; its own timestamp stays visible. Source frame indexes are never equated and missing samples are never interpolated.
- Scientific values, identity and provenance stay in their existing artifacts and processors.
- Pixi is only a temporary parity oracle during migration. It is not a second production Field path.

## Compatibility boundary

V2 remains binding outside MatchLab. Existing exact-window, chunk ownership, rights, provenance, sample-rate, source-coordinate, measurement-class, Pose topology, missing-data, tactical-method and playback behavior remains valid. MatchLab V3 does not authorize new scientific transformations or unsupported source capabilities.

