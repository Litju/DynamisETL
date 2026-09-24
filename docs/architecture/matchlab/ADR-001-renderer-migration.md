# ADR-001: Migrate MatchLab Field and Pose to Three/R3F

Status: accepted for implementation. Scope: MatchLab renderer boundary only.

## Context

Field currently uses PixiJS while Pose uses a separate Three/R3F Canvas. Separate renderers duplicate context and selection behavior and cannot share one scissored viewport surface. The package already contains Three.js, R3F and PixiJS.

## Decision

Use Three.js, React Three Fiber and Drei for the shared MatchLab world. WebGL2 is the initial production backend. Keep the current Pixi implementation only as a temporary parity oracle while Field is migrated; remove the production Field path only after complete feature and real-data acceptance. Do not add another 3D engine or a second live production Field renderer.

Scientific processors and source artifacts remain the value and provenance authorities. The new renderer does not calculate tactical or biomechanical metrics.

## Consequences

Pitch, Field and Pose share scene resources and selection/time context. Three buffer primitives replace the Pixi scene for Field after parity. WebGPU is a separate measured decision under ADR-004.

