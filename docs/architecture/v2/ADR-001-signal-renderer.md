# ADR-001: Select uPlot for dense Signals

_RES-109 benchmark-gated decision; contract version 2.0.0._

---

## 🔍 Context

Signal Laboratory currently uses a lazy ECharts Canvas wrapper for general and dense analytical charts. The workload requires exact samples, gaps, min/max display bands, playhead, brush/range, cursor, zoom, synchronized updates, and an accessible wrapper.

## 📊 Evidence

The `e315adf` browser matrix used identical 4,096/20,000/100,000-point typed arrays. At 100,000 points, median first meaningful plot was 589.0 ms for ECharts and 76.1 ms for uPlot; the measured library payloads were 1,121,883 bytes and 51,081 bytes. Feature probes passed for exact samples, gaps, bands, playhead, range/zoom, and synchronized updates.

## ✅ Decision

uPlot owns only dense temporal Signal rendering. ECharts remains the general analytical engine. The adapter must preserve unit-aware axes, BigInt-safe conversion, non-scientific reduction metadata, deterministic export, keyboard/accessibility behavior, and no recomputation from display samples.

## ⚠️ Consequences

The abandoned dense ECharts path must not remain as a second implementation. The adapter carries more product semantics than the library itself and is accepted only after the existing Signal Laboratory regression matrix passes.

