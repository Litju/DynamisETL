# DynamisData

[![CI](https://github.com/Litju/DynamisETL/actions/workflows/ci.yml/badge.svg)](https://github.com/Litju/DynamisETL/actions/workflows/ci.yml)

Compact, reproducible **multimodal human-performance data platform**: heterogeneous
sports-science datasets are ingested through source adapters, normalized into
explicit measurement contracts, validated, and served as interactive 2D/3D analysis.

> **Repository status: RES-101 V1 product.** Contracts, registry, storage
> conventions, synthetic verification, the PostgreSQL metadata schema,
> orchestration and CI exist, plus real provider adapters for Women's Soccer
> Positioning GNSS, DFL/Sportec IDSSE tracking + events, SkillCorner tracking +
> body pose, and a prepared (rights-gated, not yet acquired) SPL free-throw
> adapter. Deterministic processors, V&V and Gold marts exist (RES-100), and
> RES-101 ships the analytical API plus the interactive Performance Laboratory
> (catalog, signal/field/3D laboratories, provenance, quality and rights, dense
> Arrow transport). ML remains out of scope.

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
src/dynamis/serving/      FastAPI analytical API (gold/metadata + bounded windows)
apps/web/                 DynamisData Performance Laboratory (React/Vite product)
docker-compose.yml        PostgreSQL 18.6 (+ product and orchestration profiles)
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
pnpm install --frozen-lockfile
pnpm run web:api-check                # FastAPI OpenAPI -> TypeScript drift
pnpm run web:typecheck && pnpm run web:lint
pnpm run web:test                     # Vitest unit/component suite
pnpm run web:build                    # production workbench build
pnpm run web:e2e                      # Playwright acceptance + axe (Chromium)
```

Every V1 modality is proven by synthetic known-answer tests through
`Arrow -> Parquet(Zstd) -> DuckDB`, including schema, SI units, nullability,
monotonic time, deterministic identity and checksums. See
`tests/test_synthetic_roundtrip.py`.

CI (`.github/workflows/ci.yml`) runs the same gates on GitHub-hosted runners
against a throwaway PostgreSQL 18.6 service container and synthetic data only:
no dataset is downloaded and no external credential or repository secret is
used (the service database password is a non-secret, job-local throwaway).
Every workflow under `.github/workflows/` is itself statically validated
(actionlint) and security audited (zizmor) by
`.github/workflows/workflow-lint.yml`.

## Real-data slices (RES-97)

Two compact provider slices are implemented end to end. Data lives **outside the
repository**; CI never downloads it and the provider fixtures are structurally
synthetic.

| dataset | accepted slice | acquisition | adapter |
| --- | --- | --- | --- |
| `womens-soccer-positioning` | `J01.xlsx` (one matchday) | Zenodo Records API | streaming `openpyxl` workbook |
| `dfl-sportec-idsse` | match `J03WPY`: matchinformation + events + positions XML | Hugging Face pinned revision `a715a38d…` | streaming `lxml.iterparse` + frame-major merge |

```bash
# 1. Acquire the verified slice into immutable Bronze (never in the repository)
uv run dynamis-fetch womens-soccer-positioning --version 1.0 --key J01.xlsx --dry-run
uv run dynamis-fetch womens-soccer-positioning --version 1.0 --key J01.xlsx
uv run dynamis-fetch dfl-sportec-idsse \
  --version a715a38dfbaf5f58e431727c2b78d174101a703c --match J03WPY

# 2. Canonicalize into validated Silver Parquet + reconciliation receipts
uv run dynamis-ingest womens-soccer-positioning --version 1.0 --key J01.xlsx
uv run dynamis-ingest dfl-sportec-idsse \
  --version a715a38dfbaf5f58e431727c2b78d174101a703c --match J03WPY
```

Both commands verify the Bronze manifest before ingesting, are idempotent, and
never overwrite contradicted evidence. A verified no-download re-run is a
provenance no-op: Bronze bytes, their local SHA-256 and their first-entry
`retrieved_at` are immutable, while the run is recorded separately as a new
`verified_at` verification event. Reconciliation receipts and discovery
receipts land under `cache/receipts/`; Silver Parquet under
`silver/dataset_id=…/modality=…/session_id=…/`. The same pipeline is exposed as
Dagster assets (`womens_j01_*`, `dfl_j03wpy_*`).

**Domain authorities (audited).** The accepted DFL/Sportec positions slice
contains **3,362,853 entity-frame observations** (one object at one 25 Hz frame
tick), not 3,362,853 temporal frames: 146,211 distinct frame ticks (69,131
first half + 77,080 second half) × 23 entities per tick. The bounded-memory
constants are frozen in code: provider/spill batch **16,384** rows, merge slice
**1,024** rows, frame-major merge batch **8,192** rows, Silver Parquet row group
**65,536** rows. The Women's source publishes geographic GNSS latitude/longitude
without an explicit geodetic-datum declaration; the canonical interpretation is
WGS 84, recorded as a documented pipeline inference with no transformation
applied.

**Licensing.** `womens-soccer-positioning` is **CC BY-NC 4.0** (non-commercial,
attribution): keep it local, do not commit it or its derivatives.
`dfl-sportec-idsse` is **CC BY 4.0** (attribution). `white-cmj-acc-grf` and
`gymaware-landmine-vision` are **CC BY 4.0** (attribution, redistribution
conditional) per the reproducible rights-evidence audit in
[`sources/rights_evidence.json`](sources/rights_evidence.json). See
[`DATA_SOURCES.md`](DATA_SOURCES.md).

## 3D pose slices (RES-99)

The 3D movement branch canonicalizes provider/model-estimated pose landmarks
with explicit coordinate, availability and error semantics. Data lives **outside
the repository**; CI is structurally synthetic and never downloads it.

| dataset | accepted slice | acquisition | adapter |
| --- | --- | --- | --- |
| `skillcorner-opendata` | match `1925299`: metadata + 10 Hz tracking + 25 Hz body pose | GitHub revision `4340d274…` (tracking is Git LFS) + Hugging Face revision `a62e1ec1…` | streaming `json` + direct ZIP-member streaming |
| `spl-open-data` | `P0001/T0001` at 30 fps and 60 fps (declared, not acquired) | GitHub revision `a3f9cffb…`, behind `--acknowledge-spl-license-restrictions` | tri-file JSON, exact feet → metres |

```bash
# SkillCorner: acquire the three verified files, then canonicalize.
uv run dynamis-fetch skillcorner-opendata \
  --version 4340d274572876239c154c90bc507a9b3250a656 \
  --key data/matches/1925299/1925299_match.json \
  --key data/matches/1925299/1925299_tracking_extrapolated.jsonl \
  --key raw/1925299.jsonl.zip
uv run dynamis-ingest skillcorner-opendata \
  --version 4340d274572876239c154c90bc507a9b3250a656 \
  --key data/matches/1925299/1925299_match.json \
  --key data/matches/1925299/1925299_tracking_extrapolated.jsonl \
  --key raw/1925299.jsonl.zip
```

`pose_joint_sample` contract revision 2 carries an explicit `is_available` flag
and nullable `x/y/z`: available joints must be finite, unavailable joints carry
nulls and are never imputed. `SkeletonDefinition` declares either a `tree` or a
`landmark_set` topology; provider sources that publish no parent graph are
persisted as landmark sets with no fabricated parentage.

**Semantics preserved.** Both sources are provider/model estimates
(`MODEL_ESTIMATED`), never raw instrument measurements. SkillCorner pose keeps
the provider's own match clock, the documented 29-landmark order, the
`pose_frame = 2.5 * tracking_frame` relation and the 90th-percentile error radius
(`error_m = p90_mae_cm / 100`); X/Y are pitch-global while Z is
centroid-relative and is never interpreted as absolute player height. Pose and
tracking XY are generated separately: documented coincident frames report
timestamp/ID matching and an XY residual distribution, and are never forced to
agree. SPL coordinates are converted by the exact `0.3048` factor, session
participant identity is preserved across sessions, and session-specific keypoint
availability stays explicit.

**Out of scope here.** No joint angles, angular velocity, ROM, inverse dynamics,
smoothing, interpolation or RES-100 production metrics; no cross-provider
fusion and no ball/shot metric canonicalization.

## Performance Laboratory (RES-101)

The validated data plane is exposed as a research product:

- **API** (`src/dynamis/serving/`, `uv run dynamis-serve`): catalog, session/trial/
  stream explorer, current-revision Gold metrics with exact provenance, metric
  methodology, selected-result lineage, quality, rights, processing runs and
  bounded dense windows (JSON or Arrow IPC, `format=arrow`, ETag-cached,
  display-reduced with explicit metadata). Science is precomputed; the API never
  triggers a processor run.
- **Workbench** (`apps/web`, `pnpm --filter @dynamis/web run dev`): the
  "Dynamis Instrument" shell with URL-owned durable context, linked playhead
  across ECharts signals, the PixiJS pitch laboratory and the R3F landmark
  viewer, a selected-lineage provenance inspector, quality/rights visibility and
  measurement-class semantics. Dense windows prefer Arrow IPC decoded in a
  worker; heavy renderers are lazy chunks.

```bash
# Full-stack local workflow (PostgreSQL + API + workbench)
docker compose --profile product up -d --build
# workbench on http://localhost:8080, API on http://localhost:8000

# Development split
uv run dynamis-serve                        # API on 127.0.0.1:8000
pnpm --filter @dynamis/web run dev          # workbench on 127.0.0.1:5173 (proxies /api)
```

**Clean-clone reproduction.** From a fresh clone: `uv sync --locked`,
`pnpm install --frozen-lockfile`, copy `.env.example` to `.env`, then either the
Compose profile above or (a) `docker compose up -d postgres`, (b)
`uv run alembic upgrade head`, (c) fetch and ingest the permitted external
slices documented above, (d) run the processors and `uv run dynamis-gold all`,
(e) `uv run dynamis-serve` and `pnpm --filter @dynamis/web run dev`. Only
permitted/externally fetched data is required; nothing is committed.

**V1 acceptance evidence.** Discovery and navigation are real catalog/explorer
queries; Gold metrics and provenance are typed API responses; dense series are
windowed and display-reduced with metadata; the signal workflow, pitch replay
and 3D pose viewer share one playhead spine; deep links reproduce analytical
context; compare mode preserves dataset/subject boundaries; UI unit/component
tests, Playwright acceptance with axe scans, and the Python gates all run in
protected CI; Docker Compose runs the product locally.

## Data and license boundary

Project code is **Apache-2.0**. External datasets are governed by their own
licenses and are **never committed to Git**. `sources/registry.json` is the
machine-readable authority; [`DATA_SOURCES.md`](DATA_SOURCES.md) is the
human-readable notice, and a test enforces agreement between them.

Unclear-rights sources stay local-only. The OpenBiomechanics
professional-sports-organization / financial-analysis exclusion is preserved
verbatim, and **SPL Open Data carries its own role-dependent exclusion** from its
`LICENSE` at the pinned revision (employees/contractors/associates/significant
shareholders of professional sports organizations or financial analysis firms
need a specific written commercial license); SPL acquisition fails closed until
the operator passes `--acknowledge-spl-license-restrictions`. NC/SA data stay
outside the code license boundary.

## Out of scope so far

No ML. Dense tracking and GNSS samples never enter PostgreSQL; only their
artifact metadata and the semantic/provenance envelope do. Authentication,
organizations and collaboration UI are out of scope for V1 (single-user,
local-first).
