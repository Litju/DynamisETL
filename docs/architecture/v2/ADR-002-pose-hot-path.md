# ADR-002: Batch repeated Pose geometry

_RES-109 benchmark-gated decision; contract version 2.0.3._

---

## 🔍 Context

The current R3F Pose scene creates one independently managed joint mesh, error-radius mesh, and dynamic line object per repeated primitive. Playback updates positions and line buffers in `useFrame`.

## 📊 Evidence

The `e315adf` headless Three benchmark used one and 23 subjects with 29 landmarks plus provider, display, analytical, angle, and error layers. At 23 subjects, scene objects fell from 2,875 to 7, frame update from 0.207 ms to 0.087 ms, and the picking target map remained 667 identities. It did not render and provides no GPU draw-call measurement.

## ✅ Decision

Use shared geometries/materials, InstancedMesh for repeated joint/error glyphs, batched dynamic BufferGeometry for provider/display/analytical lines, and typed-array mutation from `useFrame`. Preserve provider/analytical/display distinction, single/all-subject modes, exact frames, camera behavior, selection mapping, and accessibility affordances. Validate actual renderer draw calls only with a rendering browser probe.

## ⚠️ Consequences

The optimized path owns GPU/object efficiency, not scientific semantics. A compatibility layer may retain the current primitive path only as a bounded migration fallback; it is not the V2 hot path.

