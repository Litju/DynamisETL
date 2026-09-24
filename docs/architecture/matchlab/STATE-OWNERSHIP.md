# MatchLab state ownership

| State | Owner | Renderer contract |
| --- | --- | --- |
| Dataset, session/match, period/trial, canonical t_ns, selected participant, layout/view | TanStack Router | Durable, validated and restorable by URL. |
| Session, streams, registered pitch dimensions, artifact metadata, exact windows and tactical outputs | TanStack Query | Bounded, rights-safe server/cache data; never copied into Zustand. |
| Live playhead, play/pause/buffering, hover and transient tactical/joint focus | Zustand | Shared by Field and Pose; frame-rate changes do not serialize into the URL. |
| Decode and frame preparation | Existing Arrow Worker through Comlink | Produces typed transferable buffers; does not change source values. |
| Camera, Three geometry and GPU buffers | R3F/Three refs | Presentation-only mutation; no per-frame React rows or scientific calculations. |
| MatchFrameContext | Derived renderer-facing snapshot and actions | The single selection/time contract over these owners; no duplicate store. |

## Selection and time transaction

The canonical player is a registered participant subject_id. Field and Pose picking call the same MatchFrameContext action. A player switch writes durable player identity and any required exact target time together, stops playback under the existing subject-switch gate, and suppresses stale prior-subject rendering until the new exact window is ready.

Live playback updates the shared Zustand playhead. A commit boundary writes canonical time to the router. Source frame selection is recomputed independently for each source; it is not converted to a shared frame index.

## Query and worker ownership

PlaybackChunkCoordinator continues to own previous/active/next chunk readiness, bounded retention, explicit BUFFERING and exact boundary handoff. Query keys remain scoped by artifact, columns, range, point budget and entity where applicable. Worker results cross the boundary as typed buffers; IDs remain a compact dictionary used for picking and accessible text.

