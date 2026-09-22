# DynamisData V2 decisions

_Benchmark-gated and negative architecture decisions frozen by RES-109._

---

## 🔍 Benchmark-gated decisions

| Decision | Frozen result | ADR |
| --- | --- | --- |
| Dense Signal renderer | uPlot for Signal Laboratory; ECharts general analytics | [ADR-001](./ADR-001-signal-renderer.md) |
| Pose hot path | InstancedMesh and batched dynamic geometry | [ADR-002](./ADR-002-pose-hot-path.md) |
| GPU backend | WebGL2 default with WebGPU seam | [ADR-003](./ADR-003-webgl2-default.md) |
| Dense read ownership | PyArrow exact; DuckDB broad reduction | [ADR-004](./ADR-004-dense-read-ownership.md) |
| Native dense service | No Rust/DataFusion in V2 | [ADR-005](./ADR-005-native-and-scientific-compute.md) |
| Scientific compute | Python/NumPy/SciPy/PyArrow | [ADR-005](./ADR-005-native-and-scientific-compute.md) |
| Continuous dense playback | Shared playhead-driven `PlaybackChunkCoordinator` with explicit `BUFFERING` and exact boundary handoff | [ADR-006](./ADR-006-continuous-playback-and-pose-camera.md) |
| Pose coordinate/camera authority | Explicit body-local vs match/world display mode and named camera ownership state machine | [ADR-006](./ADR-006-continuous-playback-and-pose-camera.md) |

## 🚫 Explicitly rejected for V2

- WebGPU as the default renderer: target browser capability did not pass.
- Rust/DataFusion dense service: Python service stayed within the frozen maximum-request budget.
- Polars rewrite: no measured transform hotspot justified replacing Arrow-native processors.
- Rust/PyO3 kernels: no measured processor hotspot justified a foreign-function boundary.
- DuckDB-Wasm in normal playback: it adds a second browser query/runtime path without a measured need.
- Kafka, Spark, and Kubernetes: no workload or deployment trigger exists in this issue.
- A second general chart engine: ECharts remains the general analytical authority.
- PostgreSQL or a time-series database for dense telemetry: Parquet remains immutable dense storage.

## 🔒 Amendment rule

An amendment must include representative evidence, an individual ADR, the updated contract/schema version when needed, and one dedicated atomic commit. A normal implementation commit cannot silently alter any selection above.
