# DynamisData V2 architecture compliance report

_RES-109 final acceptance report including the §11 manual-acceptance amendment. Raw real-data receipts remain in the external evidence cache; this report contains summary evidence only._

---

## ✅ Outcome

RES-109 is complete. The V2 contract was frozen before architecture-changing implementation, the §11 amendment is sealed as contract version 2.0.1, and the complete local scientific/backend/frontend/renderer/performance matrix is green. The branch is clean and ready for PR review against protected `main`.

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
| §11 playback/camera amendment | `f973282` | shared coordinator, reverse clock, real-browser multi-boundary acceptance |
| §11 exact-density/transient hardening | `b95028d` | uneven real-subject guard, atomic reverse start, commit-time hydration race fix |

## 📊 Before/after benchmark evidence

| Gate | Before freeze/baseline | Final | Frozen budget | Result |
| --- | ---: | ---: | ---: | --- |
| Dense Signal 100k first plot | ECharts 1,100.435 ms p95 | uPlot 144.415 ms p95 | 150 ms p95 target | Pass |
| Dense Signal 100k playhead | ECharts 91.241 ms p95 | uPlot 0.066 ms p95 | 2 ms p95 target | Pass |
| Dense Signal 100k measured heap delta | ECharts 104.5 MB | uPlot 11.4 MB | 256 MB bounded-playback budget | Pass |
| Pose 23-subject frame update | 0.64 ms p95 primitive baseline | 0.16 ms p95 optimized path | 2 ms p95 target | Pass |
| Pose 23-subject objects/draw calls | 2,875 / 2,875 | 7 / 7 | measured reduction required | Pass |
| Maximum dense service request | 959.12 ms p95 | 959.12 ms p95 current service | 1,500 ms p95 target | Pass |
| Exact White CMJ complete service | 44.52 ms p95 | 44.52 ms p95 current service | 250 ms p95 target | Pass |

The review-seal receipt used 20 browser iterations, 20 Pose iterations, 20 processor iterations, and 20 real/synthetic backend iterations. p95 values are inclusive quantiles over raw runs; no p95 claim is emitted for fewer than 20 runs. Backend complete-path values include Arrow serialization.

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

Benchmark candidates are accepted only after semantic comparison with the current dense service across normalized timestamps, identities, extrema, columns, ordering, and authoritative window metadata. The real maximum case rejected the PyArrow reduced candidate for semantic mismatch; it is not used as evidence for query ownership.

Scientific authorities, measurement classes, coordinate frames, processing provenance, rights gates, and display-reduction boundaries remain intact. No renderer consumes display samples as processor input.

## 🌐 Web and renderer gates

| Gate | Result |
| --- | --- |
| TypeScript typecheck | Passed |
| ESLint | 0 errors; 2 pre-existing warnings |
| Vitest/component tests | 138 passed across 23 files |
| Generated OpenAPI drift | Passed |
| Production Vite build | Passed; uPlot lazy chunk 51.04 kB |
| Playwright + axe + visual + responsive + lazy-loading + acceptance + renderer smoke | 57 passed |
| Real renderer smoke | uPlot, Pixi, and R3F canvas/context checks passed |
| WebGPU evaluation | WebGL2 available; WebGPU unavailable in target Chromium; WebGL2 frozen |

## 🧭 §11 continuous-playback acceptance

| Surface/evidence | Result |
| --- | --- |
| Coordinator unit matrix | 20 focused state/model tests pass; three forward boundaries, reverse buffering, seek re-plan, reverse departure from canonical maximum, exact readiness, and bounded retention covered |
| Fixture browser amendment matrix | 4 RES-109 tests pass: Pose multi-boundary exact playback/telemetry, Field forward+reverse handoff, delayed exact `BUFFERING`, and Pose seek/coordinate/camera modes |
| Real local Pose | Artifact `pose-period-1-0bbe2b182716`, subject `11897`; 440,000,000 ns → 279,437,373,508 ns at 4× over 70 s; 19 contiguous exact chunk requests / 18 boundaries; entity scope preserved; no follow-up page errors |
| Real local Field | Artifact `tracking-period-1-457d138baddf`; 0 ns → 141,127,600,000 ns at 4× over 35 s; 7 contiguous chunk requests / 6 boundaries; no entity scope; no page errors |
| Exact uneven-density guard | Pose source window reduced from 21,605 rows to 8,584 rows per real chunk after the 4× density safety guard; reduction metadata remained null |

The real receipts are substantially longer than the former approximately 16-second
cutoff and show no stale-window stop. Pose body-local and match/world display
transforms remain presentation-only; all landmark, skeleton, cue, analytical,
angle, error-radius, selection, and telemetry layers consume the same current
frame authority.

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

The implementation meets V2.0.1 and the RES-109 §11 acceptance matrix. RES-107
may proceed with production provisioning/deployment after review and merge of
the pull request. RES-107 was not started by this mission.
