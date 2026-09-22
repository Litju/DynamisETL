# DynamisData V2 dependency policy

_Frozen dependency allowlist and evidence gates for RES-109 implementation._

---

## ✅ Approved core

React, Vite, TypeScript, TanStack Router, TanStack Query, Zustand, Tailwind, local Base UI/shadcn-style components, Zod, ECharts, uPlot for dense Signals, PixiJS, Three.js, React Three Fiber, Drei, Apache Arrow, Comlink, FastAPI, Pydantic, PyArrow, DuckDB, PostgreSQL, Dagster, Alembic, dbt-DuckDB, Playwright, and axe.

## ⚙️ Conditional dependencies

| Dependency | Trigger | V2 status |
| --- | --- | --- |
| uPlot | Dense Signal benchmark winner plus interaction/accessibility parity | Selected |
| Three WebGPURenderer | Target-browser compatibility and performance evidence | Rejected as default; seam retained |
| Polars | Measured transform hotspot and deterministic contract parity | Rejected |
| Rust/PyO3 | Measured processor hotspot and stable Python boundary | Rejected |
| Rust/DataFusion | Python dense service misses maximum-request budget | Rejected |
| DuckDB-Wasm | Separate future analyst/local-SQL sandbox evidence | Not normal playback |
| three-mesh-bvh | Measured picking/spatial need after hot-path refactor | Not selected |

## 🚫 Denied without a new ADR

Redux, MobX, a second general BI chart engine, Babylon, Unity, DOM pitch replay, MongoDB for canonical/control data, Timescale/ClickHouse duplication, Kafka, Spark, Kubernetes, whole-session dense browser materialization, and opaque server-side scientific recomputation.

The CI architecture validator rejects the denied import families that are statically enforceable in application source. The contract validator does not attempt to replace package-manager or supply-chain auditing.

