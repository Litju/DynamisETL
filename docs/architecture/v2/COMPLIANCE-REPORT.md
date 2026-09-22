# DynamisData V2 architecture compliance report

_RES-109 final acceptance report including the §11 and §12 manual-acceptance amendments. Raw real-data receipts remain in the external evidence cache; this report contains summary evidence only._

---

## ✅ Outcome

RES-109 is complete only when the §11 and §12 gates below remain green at the final review head. The V2 contract is sealed as version 2.0.2, including atomic observation-aware Pose subject transitions; production resource provisioning and promotion were not performed.

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
| §12 atomic Pose subject switching | `5ccd9cd` | observation authority, exact target-time navigation, scoped retirement, switching/absence states |

## 📊 Before/after benchmark evidence

| Gate | Before freeze/baseline | Final | Frozen budget | Result |
| --- | ---: | ---: | ---: | --- |
| Dense Signal 100k first plot | ECharts 1,141.160 ms p95 | uPlot 129.270 ms p95 | 150 ms p95 target | Pass |
| Dense Signal 100k playhead | ECharts 148.567 ms p95 | uPlot 0.065 ms p95 | 2 ms p95 target | Pass |
| Dense Signal 100k measured heap delta | ECharts 503.4 MB | uPlot 22.4 MB | 256 MB bounded-playback budget | Pass |
| Pose 23-subject frame update | 1.072 ms p95 primitive baseline | 0.290 ms p95 optimized path | 2 ms p95 target | Pass |
| Pose 23-subject objects/draw calls | 2,875 / 2,875 | 7 / 7 | measured reduction required | Pass |
| Maximum dense service request | 1,129.47 ms p95 | 1,129.47 ms p95 current service | 1,500 ms p95 target | Pass |
| Exact White CMJ complete service | 64.14 ms p95 | 64.14 ms p95 current service | 250 ms p95 target | Pass |

The review-seal receipt used 20 browser iterations, 20 Pose iterations, 20 processor iterations, and 20 real/synthetic backend iterations. p95 values are inclusive quantiles over raw runs; no p95 claim is emitted for fewer than 20 runs. Backend complete-path values include Arrow serialization.

Immutable external receipt locators (SHA-256):

- Backend: `E:\Data\Temp\DynamisETL-review-backend-res109-isolated.json` — `FF65C70532DE4D835A6D4C912F07042D0B78F545E089BA6A61AF67BF1EADBE4B`
- Browser: `E:\Data\Temp\DynamisETL-review-browser-res109-isolated.json` — `EAD94C5FF640FAD0B462703D2E3CABCD3B3EFE3E8FB0A36DEA4D6CD4D75B8891`
- Pose: `E:\Data\Temp\DynamisETL-review-pose-res109-final.json` — `06348816FA81F8A174CC464692B15BBF37A61460E30E594173A0C9B5627C85F`
- Processors: `E:\Data\Temp\DynamisETL-review-processors-res109-final.json` — `E67C732FDF91443DC71B6929DD2624DBED2007FF801F73926F4D8FF64F30890A`

## 🧪 Scientific and backend gates

| Gate | Evidence | Result |
| --- | --- | --- |
| Python synthetic suite | `uv run --no-sync pytest -m "not postgres"` | 566 passed, 16 deselected |
| PostgreSQL migration suite | Docker PostgreSQL 18.6, Alembic lifecycle and repository tests | 16 passed, 566 deselected on the §12 implementation; hosted CI reruns this gate on final head |
| Processor profile | Force CMJ, IMU, GNSS/tracking, LPT, Pose, cross-sensor; synthetic + accepted/local samples | No Polars/PyO3/Rust trigger |
| Registry/rights | `dynamis.registry.main()` | Passed; 8 sources, complete modality coverage |
| Synthetic artifacts | All 8 deterministic fixtures materialized outside repository | Passed |
| Package build | `uv build --out-dir <external receipt root>` | Wheel and source distribution built |
| Dense API | Exact/reduced/entity scope/ETag/Arrow/JSON/path safety/unit metadata tests | Passed |
| Pose observation authority | Artifact/entity first/last/count, bounded exact-range observation route, unavailable-row exclusion | Passed |
| Object store | checksum, immutable repeat, range, traversal tests | 31 focused tests passed |

Benchmark candidates are accepted only after semantic comparison with the current dense service across normalized timestamps, identities, extrema, columns, ordering, and authoritative window metadata. The real maximum case rejected the PyArrow reduced candidate for semantic mismatch; it is not used as evidence for query ownership.

Scientific authorities, measurement classes, coordinate frames, processing provenance, rights gates, and display-reduction boundaries remain intact. No renderer consumes display samples as processor input.

## 🌐 Web and renderer gates

| Gate | Result |
| --- | --- |
| TypeScript typecheck | Passed |
| ESLint | 0 errors; 2 pre-existing warnings |
| Vitest/component tests | 141 passed across 24 files |
| Generated OpenAPI drift | Passed |
| Production Vite build | Passed; uPlot lazy chunk 51.04 kB |
| Playwright + axe + visual + responsive + lazy-loading + acceptance + renderer smoke | 63 passed; optional real-data test skipped without its external fixture and passed separately |
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

## 🧭 §12 atomic subject-switch acceptance

| Surface/evidence | Result |
| --- | --- |
| Atomic transition | Stop playback → clear subject/joint/hover transient state → retire only prior subject scope → resolve exact target → navigate subject + `t_ns` together → replace coordinator → render after exact readiness |
| Observation authority | Artifact/entity first/last observed canonical time and observed-frame count; bounded range route handles a first observation inside an explicit range |
| UI semantics | Observed frame, temporary absence, no Pose in period/range, and Switching/loading are distinct; no-frame telemetry never lists every landmark as provider-unavailable |
| Browser regression matrix | Paused >10 s, playing, BUFFERING, numeric ID, body-local individual, all-subject focus, first observation >0, temporary absence, no Pose, reload/back-forward, and replacement-request survival |
| Real local SkillCorner switch | Paused at `11897` / 17,417,738,000 ns → `50999` / first observation 32,920,000,000 ns; exact selected-range response returned 18,763 rows; switching back resolved `11897` to its first exact observation in the active range (23,440,000,000 ns); no page errors |

The real local browser receipt uses the period-1 source Parquet. The bounded
fixture contains only the selected subject rows and remains outside the repo.
The reproduction harness is [res109-real-data.spec.ts](../../../apps/web/e2e/res109-real-data.spec.ts)
and [prepare-res109-real-pose.py](../../../apps/web/e2e/prepare-res109-real-pose.py).

- Source artifact: `silver/dataset_id=skillcorner-opendata/modality=pose/session_id=1925299/pose-period-1.parquet`, SHA-256 `0bbe2b182716bda3307b316e3c307ef2470753f9ced05a73fb24effcfe412da4`
- Bounded fixture: `E:\Data\Temp\DynamisETL-res109-real-pose-fixture.json`, SHA-256 `3FD6EACD800F6A1AF9389FC70215B75A8EB98E536C66E5B6FC59D66D6720F193`
- Browser receipt: `E:\Data\Temp\DynamisETL-res109-real-subject-switch.json`, SHA-256 `D7EAFBADAABC3CB98B01524A45EE78C3ADA946DEA533BB68B84FF92BD9AC7A96`

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

The implementation meets V2.0.2 and the RES-109 §11 + §12 acceptance matrix. RES-107
may proceed with production provisioning/deployment after review and merge of
the pull request. RES-107 was not started by this mission.
