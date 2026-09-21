# ADR-005: Keep the Python scientific and dense service authorities

_RES-109 benchmark-gated negative decisions; contract version 2.0.0._

---

## 🔍 Context

RES-109 permits Polars, Rust/PyO3, and Rust/DataFusion only when representative measured triggers justify new boundaries. The current processors are deterministic Python/NumPy/SciPy/PyArrow code, and FastAPI owns the control/scientific API contract.

## 📊 Evidence

The `e315adf` processor matrix measured existing Force CMJ, IMU, locomotor, LPT, Pose, and cross-sensor workloads, including accepted/local force, IMU, and 100,000-row tracking samples. No processor hotspot or deterministic transform gap justified a Polars or Rust/PyO3 boundary. The maximum accepted/local dense request remained within the 1.5 s V2 service budget, so Rust/DataFusion did not trigger.

## ✅ Decision

Keep Python, NumPy, SciPy, and PyArrow as scientific authorities. Keep FastAPI as control/scientific API authority. Do not add Polars, PyO3, Rust, or DataFusion to V2. If a future measured trigger is met, the replacement must sit behind the existing processor or Arrow service contract and receive a new ADR/contract version.

## ⚠️ Consequences

The architecture accepts a smaller runtime surface and avoids a second scientific semantics implementation. Performance work remains available through vectorization, batching, PyArrow/DuckDB query ownership, and bounded transport.

