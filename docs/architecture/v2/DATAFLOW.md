# DynamisData data flow

_Concrete source-to-renderer flows after the RES-109 §11 amendment._

---

## 📥 Canonical ingestion flow

```mermaid
flowchart LR
    accTitle: Canonical ingestion flow
    accDescr: Accepted source members are verified, canonicalized into Arrow batches, validated, persisted as immutable Parquet, and registered with provenance and rights metadata.

    source[📥 Accepted source] --> verify[🔐 Verify identity and rights]
    verify --> adapter[⚙️ Adapter canonicalization]
    adapter --> validate[🧪 Contract and quality checks]
    validate --> silver[(💾 Silver Parquet)]
    validate --> receipt[📝 Provenance receipt]
    silver --> artifact[🏷️ Artifact identity]
    artifact --> gold[(💾 Gold/control metadata)]
```

The acquisition layer refuses unverified or rights-incompatible materialization. Adapters preserve source/provider semantics while adding explicit SI units, clocks, synchronization, coordinate frames, measurement classes, and declared provenance. The persistence path uses atomic writes and deterministic artifact identity.

## 🌐 Analytical request flow

```mermaid
sequenceDiagram
    accTitle: Analytical request flow
    accDescr: The workbench resolves durable context, obtains cached control metadata, requests a bounded dense window, and decodes the Arrow response off the main thread.

    participant url as 🌐 Router URL
    participant query as ⚙️ Query cache
    participant api as 🖥️ FastAPI
    participant control as 💾 PostgreSQL/Gold
    participant dense as 💾 Parquet reader
    participant worker as 📦 Arrow worker
    participant view as 📊 Laboratory view

    url->>query: Dataset/session/stream context
    query->>api: Catalog/session/artifact request
    api->>control: Read control metadata
    control-->>api: Contract-shaped metadata
    api-->>query: Cached metadata
    query->>api: Bounded dense window request
    api->>dense: Read exact or display-reduced range
    dense-->>api: Arrow table + metadata
    api-->>query: Arrow stream + ETag
    query->>worker: Transfer buffer
    worker-->>view: Typed arrays + BigInt time
    view-->>url: Commit only explicit navigation changes
```

## 🔄 Playback flow

The shared `PlaybackChunkCoordinator` plans canonical previous/active/next
chunks from the transient BigInt playhead. Query owns Arrow/JSON data and
prefetches adjacent chunks; the coordinator changes active identity only at a
boundary, clamps the clock in explicit `BUFFERING` when an exact next chunk is
not ready, and evicts outside the three-chunk cache. Pose and Field use exact
handoff data; dense Signals retain explicit display-reduction metadata.

```mermaid
flowchart TB
    accTitle: Current playback flow
    accDescr: The current shared clock advances transient Zustand state while renderers sample the loaded window; URL state changes only at explicit commit boundaries.

    selected[👤 Selected context] --> coordinator[🧭 PlaybackChunkCoordinator]
    coordinator --> previous[📦 Previous cache]
    coordinator --> active[▶️ Active exact/display chunk]
    coordinator --> next[📦 Prefetched next cache]
    active --> clock[⚡ Zustand BigInt playhead]
    clock --> signal[📊 Signal renderer]
    clock --> field[🎨 Pixi field renderer]
    clock --> pose[🎨 Three pose renderer]
    next -. not ready .-> buffering[⏸️ BUFFERING]
    buffering --> coordinator
    clock --> commit[🏷️ Explicit URL commit]
```

## 📦 Artifact identity flow

Artifact identity is carried from external file to serving response. The dense API never accepts an arbitrary path; it resolves a registered relative path beneath the configured dataset root and checks the expected Parquet extension/file boundary. Response metadata carries artifact identity, canonical time bounds, units, coordinate frame, measurement class, source/returned row counts, reduction details, and a display note.
