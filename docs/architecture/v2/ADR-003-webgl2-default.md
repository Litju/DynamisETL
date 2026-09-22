# ADR-003: Freeze WebGL2 as the V2 GPU default

_RES-109 benchmark-gated decision; contract version 2.0.0._

---

## 🔍 Context

Three WebGPURenderer was evaluated only after the Pose hot-path prototype, with deterministic WebGL2 fallback required by the issue.

## 📊 Evidence

The local target Chromium probe reported WebGL2 available and WebGPU unavailable under the reproducible headless flags. No target-browser compatibility/performance result justified making WebGPU an unconditional dependency.

## ✅ Decision

WebGL2 remains the V2 default. Keep a narrow future WebGPURenderer seam and rerun the decision only with a target-browser feature/performance receipt after the optimized scene exists.

## ⚠️ Consequences

V2 does not ship unused experimental WebGPU production code. The Three authority remains unchanged, and a future WebGPU experiment must preserve all scientific layers and WebGL2 fallback behavior.

