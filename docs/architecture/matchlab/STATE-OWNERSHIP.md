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

The canonical player is a registered participant subject_id. Field and Pose picking call the same MatchFrameContext action. A Field-origin pick preserves the current canonical time and, when Pose has no valid frame within its source tolerance, displays absence and the next observed time. A Pose-origin subject switch retains RES-109 section 12: stop playback, resolve the first valid observation in the active range, then commit the new subject and exact target together. The existing switch gate suppresses stale prior-subject rendering until the replacement window is ready.

Live playback updates the shared Zustand playhead. A commit boundary writes canonical time to the router. Each source resolves its latest real sample at or before that time within its own declared sampling tolerance. The source timestamp remains distinct from the playhead; missing samples are never interpolated and frame indexes are not shared.

## Query and worker ownership

PlaybackChunkCoordinator continues to own previous/active/next chunk readiness, bounded retention, explicit BUFFERING and exact boundary handoff. Query keys remain scoped by artifact, columns, range, point budget and entity where applicable. Worker results cross the boundary as typed buffers; IDs remain a compact dictionary used for picking and accessible text.

