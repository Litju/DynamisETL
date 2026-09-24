# MatchLab V3 architecture

Status: frozen for the MatchLab rendering boundary. Contract: architecture/system-v3.json.

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
- Tracking/Pose frames resolve independently against one signed BigInt canonical time. Source frame indexes are never equated.
- Scientific values, identity and provenance stay in their existing artifacts and processors.
- Pixi is only a temporary parity oracle during migration. It is not a second production Field path.

## Compatibility boundary

V2 remains binding outside MatchLab. Existing exact-window, chunk ownership, rights, provenance, sample-rate, source-coordinate, measurement-class, Pose topology, missing-data, tactical-method and playback behavior remains valid. MatchLab V3 does not authorize new scientific transformations or unsupported source capabilities.

