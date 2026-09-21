# ADR-004: Split exact and reduced dense read ownership

_RES-109 benchmark-gated decision; contract version 2.0.0._

---

## 🔍 Context

The dense API must serve exact/reduced windows without moving telemetry into PostgreSQL. PyArrow dataset operations and DuckDB Parquet SQL can express overlapping query classes, but complete endpoint cost and reduction semantics decide ownership.

## 📊 Evidence

The `e315adf` accepted/local matrix showed PyArrow leading exact and ordinary scoped windows. The broad maximum class measured 2,228.46 ms for a direct PyArrow reduction candidate, 1,161.03 ms for direct DuckDB reduction, and 907.81 ms for the current complete service. Synthetic CI cases preserved exact/reduced row budgets for all candidate paths.

## ✅ Decision

PyArrow owns exact and ordinary scoped windows. DuckDB owns broad/max display reduction and keeps the existing min/max SQL semantics. Both paths remain behind the unchanged FastAPI dense request/response contract, with entity scoping before reduction and complete metadata.

## ⚠️ Consequences

Query ownership is explicit rather than a global engine rewrite. Any future replacement must prove identical row identity, reduction metadata, units, provenance, and rights behavior against the same complete endpoint workload.

