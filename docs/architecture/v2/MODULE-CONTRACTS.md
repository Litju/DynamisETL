# DynamisData V2 module contracts

_Executable ownership summary for the frozen V2 module graph._

---

## 📋 State and dependency contracts

| Module | Runtime owner | State owner | Permitted dependency boundary | Forbidden boundary |
| --- | --- | --- | --- | --- |
| Product shell | React/Vite | component state | local UI, Router, Query, Zustand | Redux/MobX, server duplication |
| Durable context | TanStack Router | URL | validated search params | frame-cadence URL writes |
| Server cache | TanStack Query | Query cache | OpenAPI, Arrow, Comlink | server data in Zustand |
| Transient state | Zustand | analysis store | BigInt time, selection | scientific values, React frame updates |
| General analytics | ECharts | input/query state | ECharts wrapper | dense dual renderer |
| Dense Signal | uPlot adapter | WindowTable + transient state | uPlot, TypedArrays, Arrow | smoothing, row objects, recomputation |
| Field | PixiJS | imperative Pixi scene | Pixi, typed frame models | DOM/Three pitch replay |
| Pose | Three/R3F | refs + Zustand selection | Instancing, dynamic buffers | per-primitive hot-path churn |
| Browser dense plane | Arrow Worker | worker-local buffers | Arrow, Comlink, transferables | DuckDB-Wasm playback |
| Control API | FastAPI | request/backend | Pydantic, OpenAPI, SQLAlchemy | processor execution |
| Dense read plane | PyArrow/DuckDB | request-local | Parquet scan/reduction | Rust without trigger |
| Scientific compute | Python processors | processor/artifact contract | NumPy, SciPy, PyArrow | display data as input |
| Artifact plane | S3-compatible/local adapter | artifact identity | private object/file IO | public restricted URLs |
| PostgreSQL plane | PostgreSQL/Neon | database transaction | SQLAlchemy/Alembic | dense telemetry storage |
| Runtime readiness | Cloud Run container | environment contract | Docker/Uvicorn | Vercel dense API, Kubernetes |

## 📦 Input/output invariants

Every module in `system-v2.json` declares an input authority, output authority, transport, storage authority, hot-path ownership, and fallback. The following cross-module invariants are mandatory:

- canonical signed time is preserved through Arrow and converted to renderer units only at the display boundary;
- display reduction carries method, parameters, source points, returned points, units, coordinate frame, measurement class, and an explicit non-scientific note;
- exact Pose frames are never reduced;
- entity/subject scope is applied before a window is reduced or rendered;
- provider skeleton, analytical segments, view-only cues, angle arcs, error radii, and selection identity remain separate layers;
- immutable artifacts remain checksum-bound and rights-safe;
- processor code SHA, method, parameters, source artifact, and output artifact remain reconstructable;
- no renderer imports or invokes scientific processors.

## 🔗 Contract references

- Machine-readable contract: [`architecture/system-v2.json`](../../../architecture/system-v2.json)
- JSON schema: [`architecture/system-v2.schema.json`](../../../architecture/system-v2.schema.json)
- Validator: [`scripts/validate_architecture.py`](../../../scripts/validate_architecture.py)
- CI gate: [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml)

