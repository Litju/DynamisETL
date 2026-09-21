# DynamisData data flow

_Concrete source-to-renderer flows observed on protected `main` before RES-109 refactoring._

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

The current playback path requests a selected window up front and advances a shared BigInt playhead. It is not yet a bounded previous/active/next chunk pipeline; Pose and Signal views consume the same selected context but do not share a canonical chunk cache.

```mermaid
flowchart TB
    accTitle: Current playback flow
    accDescr: The current shared clock advances transient Zustand state while renderers sample the loaded window; URL state changes only at explicit commit boundaries.

    selected[👤 Selected context] --> request[🌐 Query selected window]
    request --> loaded[📦 Arrow table in query cache]
    loaded --> clock[⚡ Zustand BigInt playhead]
    clock --> signal[📊 Signal renderer]
    clock --> field[🎨 Pixi field renderer]
    clock --> pose[🎨 Three pose renderer]
    clock --> commit[🏷️ Explicit URL commit]
```

## 📦 Artifact identity flow

Artifact identity is carried from external file to serving response. The dense API never accepts an arbitrary path; it resolves a registered relative path beneath the configured dataset root and checks the expected Parquet extension/file boundary. Response metadata carries artifact identity, canonical time bounds, units, coordinate frame, measurement class, source/returned row counts, reduction details, and a display note.

