# DynamisData V2 architecture compliance report

_RES-109 final acceptance report at the current protected `main` tip. Raw real-data receipts remain in the external evidence cache; this report contains summary evidence only._

---

## ✅ Outcome

RES-109 is complete. The V2 contract was frozen before architecture-changing implementation, all implementation units conform to [`architecture/system-v2.json`](../../../architecture/system-v2.json), and the complete local scientific/backend/frontend/renderer/performance matrix is green. The branch is clean and ready for a pull request against protected `main`.

Production resource provisioning and promotion were not performed; that remains RES-107 scope.

## 🔒 Contract and implementation history

| Milestone | Commit | Result |
| --- | --- | --- |
| Current-system investigation | `76f9656` | Actual module/dataflow/hot-path inventory |
| Benchmark matrix | `e315adf` | Real/local + synthetic selection evidence |
| V2 contract freeze | `2b4f33b` | Schema-validated frozen architecture and ADRs |
| Dense Signal renderer | `4bd8f3b` | uPlot adapter; dense ECharts path removed |
| Pose hot path | `cf35acd` | Instanced/batched WebGL2 path |
| Bounded chunk pipeline | `2f4ead9` | Deterministic previous/active/next planning and prefetch |
| Dense read ownership | `96cab06` | PyArrow exact path; DuckDB reduction path |
| Object plane | `3c7e1f0` | Local + private S3-compatible/R2-ready adapter |
| Runtime readiness | `132aade` | readiness, healthcheck, pooling, bounded access log, `PORT` |
| Locked test import gates | `e8183d4`, `509f47b` | repository scripts and pytest path work in CI runtime |

## 📊 Before/after benchmark evidence

| Gate | Before freeze/baseline | Final | Frozen budget | Result |
| --- | ---: | ---: | ---: | --- |
| Dense Signal 100k first plot | ECharts 589.0 ms | uPlot 91.7 ms | 150 ms p95 target | Pass |
| Dense Signal 100k playhead | ECharts 41.31 ms | uPlot 0.025 ms | 2 ms p95 target | Pass |
| Dense Signal 100k measured heap delta | ECharts 104.5 MB | uPlot 11.4 MB | 256 MB bounded-playback budget | Pass |
| Pose 23-subject frame update | 0.445 ms primitive baseline | 0.135 ms optimized path | 2 ms p95 target | Pass |
| Pose 23-subject objects/draw calls | 2,875 / 2,875 | 7 / 7 | measured reduction required | Pass |
| Maximum dense service request | 907.81 ms p50 | 801.34 ms p50 | 1,500 ms p95 target | Pass |
| Exact White CMJ complete service | 56.76 ms p50 | 55.99 ms p50 | 250 ms p95 target | Pass |

The final acceptance receipt used 5 browser iterations, 20 Pose iterations, and 3 iterations for each real/synthetic backend case. Local p50 values vary with cache and workstation load; the frozen decisions use the workload class and complete-path budget, not a single microbenchmark.

## 🧪 Scientific and backend gates

| Gate | Evidence | Result |
| --- | --- | --- |
| Python synthetic suite | `uv run --no-sync pytest -m "not postgres"` | 562 passed, 16 deselected |
| PostgreSQL migration suite | Docker PostgreSQL 18.6, Alembic lifecycle and repository tests | 16 passed, 562 deselected |
| Processor profile | Force CMJ, IMU, GNSS/tracking, LPT, Pose, cross-sensor; synthetic + accepted/local samples | No Polars/PyO3/Rust trigger |
| Registry/rights | `dynamis.registry.main()` | Passed; 8 sources, complete modality coverage |
| Synthetic artifacts | All 8 deterministic fixtures materialized outside repository | Passed |
| Package build | `uv build --out-dir <external receipt root>` | Wheel and source distribution built |
| Dense API | Exact/reduced/entity scope/ETag/Arrow/JSON/path safety/unit metadata tests | Passed |
| Object store | checksum, immutable repeat, range, traversal tests | 31 focused tests passed |

Scientific authorities, measurement classes, coordinate frames, processing provenance, rights gates, and display-reduction boundaries remain intact. No renderer consumes display samples as processor input.

## 🌐 Web and renderer gates

| Gate | Result |
| --- | --- |
| TypeScript typecheck | Passed |
| ESLint | 0 errors; 2 pre-existing warnings |
| Vitest/component tests | 133 passed across 22 files |
| Generated OpenAPI drift | Passed |
| Production Vite build | Passed; uPlot lazy chunk 51.04 kB |
| Playwright + axe + visual + responsive + lazy-loading + acceptance + renderer smoke | 53 passed |
| Real renderer smoke | uPlot, Pixi, and R3F canvas/context checks passed |
| WebGPU evaluation | WebGL2 available; WebGPU unavailable in target Chromium; WebGL2 frozen |

## 📦 Runtime and deployment readiness

- API container remains non-root, healthchecked, `PORT`-aware, and Cloud Run-oriented.
- `/api/health` is liveness-only; `/api/ready` exercises the serving dependency.
- PostgreSQL pooling is bounded by environment-configured size, overflow, and timeout.
- Access logs are bounded JSON records without query strings or sensitive headers.
- Private S3-compatible/R2-ready object adapter and local filesystem adapter are provider-neutral; no live bucket was created.
- `docker compose config --quiet` passed; no live production resource was provisioned.

## ⚠️ Accepted limitations

- Existing ESLint hook warnings and dependency deprecation warnings remain outside RES-109 scope; they do not fail gates.
- WebGPU cannot be selected without target-browser support and a new measured receipt.
- Cloud Run CPU/memory/concurrency values are readiness expectations, not live deployment measurements, because RES-107 owns provisioning.
- The workstation emitted pytest cache permission warnings while writing the existing repository cache; all acceptance runs used an external basetemp and passed.

## 🏁 Closure decision

The implementation meets the frozen V2 contract and the RES-109 acceptance matrix. RES-107 may proceed with production provisioning/deployment after review of the pull request. RES-107 was not started by this mission.

