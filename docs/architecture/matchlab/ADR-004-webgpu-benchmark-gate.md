# ADR-004: Benchmark WebGPU only on the final MatchLab scene

Status: accepted for implementation; decision deferred until benchmark evidence exists.

## Decision

Ship the migration on WebGL2. After Field, Pose, tactical scalar surfaces, split views and required materials exist, benchmark the identical representative scene on WebGL2 and Three WebGPURenderer/WebGPU. Include required TSL/NodeMaterial-ready materials where practical. Test Field-only, Pose-only and split Field/Pose at 1600x1000 and 1440x900.

Record target-browser compatibility, main-thread time, worker preparation time, GPU frame time when available, draw calls, heap, chunk handoff and selection latency. Adopt WebGPU only if its compatibility and measured performance justify it; retain a WebGL2 fallback.

## Consequences

An early empty-scene benchmark cannot select the backend. The default is unchanged until representative evidence is collected. A measured keep-WebGL2 result is a valid decision.

