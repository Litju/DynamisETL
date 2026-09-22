# DynamisData hot paths

_Measured candidates and current high-frequency ownership identified before the RES-109 contract freeze._

---

## ⚡ Browser hot paths

| Path | Current work | State/update cadence | Risk to measure |
| --- | --- | --- | --- |
| Signal first render | ECharts lazy import, Canvas init, option construction, series/band allocation | Query update | Initialization and heap cost at 4k/20k/100k points |
| Signal interaction | ECharts dataZoom/click, range conversion, playhead option replacement | Pointer/transport event | Frame cost and interaction latency |
| Arrow decode | Worker IPC, `tableFromIPC`, typed-array copies | Window request | Decode time and transferred bytes |
| Playback clock | `requestAnimationFrame`, BigInt arithmetic, Zustand `setPlayhead` | Every animation frame | Subscriber/render invalidation cost |
| Field replay | Pixi imperative clear/redraw of shared Graphics | Every frame while playing | CPU frame and selection traversal |
| Pose single subject | `useFrame`, landmark map, mesh position mutation, dynamic line updates | Every frame while playing | Scene objects, CPU frame, picking; GPU draw calls require a rendering browser probe |
| Pose all subjects | Flattened frames, per-subject scene branches, camera framing | Every frame while playing | 23 × 29 landmark scaling and memory |

## 🖥️ Serving hot paths

| Path | Current owner | Work | Receipt required |
| --- | --- | --- | --- |
| Control read | PostgreSQL backend/repository | Metadata joins and Gold reads | p50/p95 latency |
| Dense exact window | DuckDB SQL over Parquet | Filter time/entity and project columns | bytes, scan, serialization, memory, p50/p95 |
| Dense reduced window | DuckDB SQL aggregation over Parquet | Per-identity min/max buckets | bytes, scan, serialization, memory, p50/p95 |
| Arrow response | FastAPI response builder | IPC serialization and ETag | payload bytes and serialization time |
| Browser decode | Comlink worker | IPC stream decode to TypedArrays | decode duration and heap delta |

The current dense implementation already enforces a source-row cap before reduction. It scopes entity requests before applying display reduction, which is required for exact pose replay. The benchmark will compare the complete endpoint cost for PyArrow dataset-style access and DuckDB Parquet SQL where both can express the same contract; it will not select an engine from isolated microbenchmarks.

## 🧪 Scientific-compute candidates

The installed dependency set includes NumPy, SciPy, PyArrow, DuckDB, and Polars. Repository processors use NumPy/SciPy/PyArrow and deterministic batch contracts. Polars and Rust/PyO3 are therefore benchmark candidates only, not proposed migrations. The hotspot benchmark will report processor wall time and allocation/row counts, then record an explicit keep decision if no material gain is demonstrated without contract changes.

## 🔐 Scientific boundaries

The following are protected at every hot path:

- canonical time stays signed and BigInt-safe until a renderer conversion boundary;
- exact pose frames are never display-reduced;
- min/max display bands are never processor inputs;
- subject/entity scope is explicit and never inferred by merging rows;
- provider skeleton, analytical segments, display cues, angle semantics, error radii, coordinate frames, units, and measurement class remain distinct;
- source, derived, annotation, expected-output, and oracle evidence remain separately identifiable;
- rights and provenance checks remain outside visualization code.

