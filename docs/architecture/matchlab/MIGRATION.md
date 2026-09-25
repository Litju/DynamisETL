# MatchLab V3 migration

Entry commit: ae0164c68e44ebec64360a4475c250f4def86311 on protected main, after the accepted RES-110/112 baseline. Execute in one worktree with one atomic commit per coherent migration unit. Record each gate and commit in RES-113.

## Ordered gates

1. Freeze and validate the V3 contract, schema and ADRs before renderer implementation.
2. Establish MatchFrameContext for match, period, canonical time, player and selection.
3. Implement bidirectional Field/Pose player selection and canonical-time behavior.
4. Build a source-sized procedural Pitch3D from registered structured metadata.
5. Implement reusable Tracking, Tactical, Pose and Context Three layers.
6. Move tracking, Pose and tactical preparation into the existing Arrow/Comlink worker with transferable typed buffers.
7. Implement one R3F Canvas and Drei scissored multi-view support.
8. Migrate Field from Pixi to Three/R3F. Retain Pixi only as a temporary parity oracle.
9. Implement fixed-domain heatmap, contour and optional analytical elevation for processor-produced scalar fields.
10. Prove real SkillCorner cross-selection and synchronized playback.
11. Benchmark WebGL2 against WebGPU only on the final representative Field, Pose and split scene.
12. Remove production Pixi Field code only after full parity and real-data acceptance.
13. Apply the RES-113 §§21–22 hybrid Field amendment: Tactical Map default, Structure Lift, metric-specific scalar elevation, centralized presentation depths, Structure Lift-only analytical shadows, and real DFL/SkillCorner acceptance evidence.

Every renderer step retains source identities, source measurement class, units, provider state, coordinate frames, missing-sample behavior, rights checks, checksum-bound artifact lineage, canonical clocks and processor-owned metrics. A visual transform cannot become a scientific input.

## Acceptance evidence

- Contract validator, typecheck, relevant unit/browser fixture checks and generated API drift check pass.
- Field and Pose selection in both directions agrees on canonical player identity and playhead. Missing exact Pose observations show explicit absence and observation bounds without changing player or time.
- Forward/reverse playback crosses exact chunk boundaries with explicit BUFFERING, no stale frame, gap fabrication or renderer churn.
- Pixi parity evidence covers player, ball, event, selection, trail, tactical overlay, coordinate and playback behavior before its production path is removed.
- Real SkillCorner Field/Pose browser acceptance reports source frame IDs and canonical time independently and has no console errors.
- WebGL2/WebGPU evidence uses the final representative scene at both contracted sizes and records compatibility, frame time, worker preparation, draw calls, heap and selection latency.
- Tactical Map and Structure Lift are benchmarked separately at the contracted sizes. Structure Lift reports paired shadow-enabled/shadow-disabled timing and scalar-surface update cost.
- Real DFL and SkillCorner evidence records orthographic Tactical Map, Structure Lift, declared analytical elevation and restrained pitch shadow, accepted tactical structure, and split Field orthographic + Pose 3D synchronization.
- The owner reviews and explicitly accepts RES-113. RES-111 and RES-114 remain blocked until then.

## RES-113 §§21–22 review receipt

Captured real-browser evidence is in `output/playwright/res-113/final/`; the acceptance path is `apps/web/e2e-real/res113-evidence.spec.ts`. The hybrid WebGL2 receipt is `output/playwright/res-113/hybrid-field-benchmark.json`; the renderer comparison is `output/playwright/res-113/renderer-benchmark.json`. The hybrid benchmark uses a two-second warm-up and five-second measurement at both contracted viewport sizes. All eight Tactical Map, Structure Lift shadow-off/on, and split scenarios completed without browser errors. Structure Lift's directional shadow map measured p95 0.2 ms at both sizes; scalar mesh update p95 was 0.7 ms at 1600×1000 and 1.3 ms at 1440×900 with shadows enabled. Tactical Map measured 57/56 FPS; Structure Lift measured 57/56 FPS with shadows off and 54/55 FPS with shadows on; split measured 57/54 FPS. Raw frame intervals, selection latency and shadow samples remain in the receipt.

The WebGPU comparison also completed all twelve Field, Pose and split runs without renderer or console errors. In this workstation sample, WebGPU Field/Pose/split measured 51/56/9 FPS at 1600×1000 and 58/57/16 FPS at 1440×900, while WebGL2 measured 59/58/50 and 60/58/52 FPS. WebGPU split p95 frame intervals were 200/166.7 ms, versus 33.4/33.4 ms on WebGL2. Keep WebGL2 as the production backend.

RES-113 remains **In Progress** until the owner visually reviews and accepts the hybrid Field. The evidence receipt does not itself satisfy that review gate.

