# DynamisData

Compact, reproducible **multimodal human-performance data platform**: heterogeneous
sports-science datasets are ingested through source adapters, normalized into
explicit measurement contracts, validated, and served as interactive 2D/3D analysis.

> **Repository status: RES-96 foundation.** Contracts, registry, storage
> conventions, synthetic verification, the PostgreSQL metadata schema, the
> orchestration skeleton and CI exist. Provider adapters, production metrics, ML
> and the visualization product are later issues.

## V1 product boundary

- One canonical platform; **no subject-level fusion across unrelated datasets**.
  Unification happens at measurement semantics, not identity:
  `dataset -> subject -> session -> trial/period -> device -> stream -> sample -> run -> metric`.
- Raw/native data are immutable; canonical data use **SI units**, explicit
  timebases and explicit coordinate frames.
- Every value is classified `RAW_MEASURED`, `SOURCE_DERIVED`, `PIPELINE_DERIVED`
  or `MODEL_ESTIMATED`.
- V1 is deterministic scientific/data engineering. ML is out of scope.
- Compact corpus first; SoccerMon-scale ingestion is a future benchmark and is
  **not** a V1 dependency.

## Architecture

Medallion + Ports & Adapters + one anti-corruption layer per provider:

```
bronze/native files -> typed adapter -> canonical/silver Parquet -> QC/V&V
   -> gold marts -> PostgreSQL serving -> FastAPI -> React visual laboratory
```

Dense analytical scans run directly over Parquet with **DuckDB**. **PostgreSQL**
stores the registry, provenance, algorithms, quality results and curated serving
marts. **Dagster** owns asset lineage and orchestration.

**Parquet is authoritative for dense signals.** High-frequency samples never
enter PostgreSQL; only artifact metadata does.

## Repository layout

```
src/dynamis/
  config.py               machine-local root resolution (.env / environment)
  guard.py                repository boundary guard (no data, secrets, paths)
  contracts/              SINGLE domain/contract authority
    domain.py             DatasetSource ... DerivedMetric, LicensePolicy
    enums.py              Modality, MeasurementClass, SessionKind, ...
    units.py              Pint-backed SI authority, explicit conversion
    frames.py             CoordinateFrame, FrameTransform, SkeletonDefinition
    sync.py               Clock, SynchronizationSpec, SyncAlignment
    schemas.py            7 typed PyArrow modality schemas + registry
    invariants.py         cross-entity invariants (multi-subject sessions, ...)
  registry.py             registry loader, rights audit, CLI
  fixtures/               deterministic synthetic fixtures per modality
  quality/                contract checks + typed pyarrow.compute boundary
  storage/                paths, atomic Parquet+Zstd, Bronze manifests, DuckDB
  orchestration/          Dagster assets and Definitions
infra/migrations/         Alembic environment + bootstrap revision
sources/registry.json     machine-readable dataset/source registry
apps/web/                 pnpm workspace placeholder (RES-101 builds the product)
docker-compose.yml        PostgreSQL 18.6 (+ optional Dagster profile)
```

External roots are configured, never hard-coded:

| root | purpose | layers |
| --- | --- | --- |
| `DYNAMIS_DATASET_ROOT` | scientific data | `bronze/ silver/ gold/ quarantine/ cache/ tmp/` |
| `DYNAMIS_DATABASE_ROOT` | engine state | `postgres/ duckdb/` |

## Bootstrap

```bash
# 1. Runtime authorities: CPython 3.12, Node.js 24 LTS, pnpm 11
uv sync --locked
pnpm install --frozen-lockfile

# 2. Local configuration (git-ignored; .env.example documents every variable)
cp .env.example .env

# 3. Services: PostgreSQL 18.6 (Dagster is profile-gated)
docker compose up -d postgres
docker compose --profile orchestration up -d

# 4. Metadata schema
uv run alembic upgrade head
```

PostgreSQL 18 changed its volume root: `docker-compose.yml` bind-mounts
`${DYNAMIS_DATABASE_ROOT}/postgres` at `/var/lib/postgresql` (not
`/var/lib/postgresql/data`).

## Verification

```bash
uv run ruff format --check .          # formatting
uv run ruff check .                   # lint
uv run pyright                        # types
uv run pytest                         # full suite (PostgreSQL suite needs DYNAMIS_TEST_POSTGRES_URL)
uv run pytest -m "not postgres"       # synthetic-only, no services required
uv run dynamis-registry-validate      # registry + rights audit
uv run dynamis-synthetic-materialize  # Arrow -> Parquet+Zstd, contract-checked
python scripts/guard_repository.py    # repository boundary
```

Every V1 modality is proven by synthetic known-answer tests through
`Arrow -> Parquet(Zstd) -> DuckDB`, including schema, SI units, nullability,
monotonic time, deterministic identity and checksums. See
`tests/test_synthetic_roundtrip.py`.

## Data and license boundary

Project code is **Apache-2.0**. External datasets are governed by their own
licenses and are **never committed to Git**. `sources/registry.json` is the
machine-readable authority; [`DATA_SOURCES.md`](DATA_SOURCES.md) is the
human-readable notice, and a test enforces agreement between them.

Unclear-rights sources stay local-only, and the OpenBiomechanics
professional-sports-organization / financial-analysis exclusion is preserved
verbatim. NC/SA data stay outside the code license boundary.

## Out of scope for RES-96

No real dataset download, no provider adapters, no production metrics, no final
visualization UI, no ML, no RES-97+ work.
