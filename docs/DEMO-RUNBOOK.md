# DynamisData demo runbook — MatchLab flagship workstation

This runbook takes a machine with the accepted local corpus to a workbench whose flagship
MatchLab route integrates Field, selected-player Pose and the Analysis Dashboard, and fails loudly when it cannot. Nothing here
downloads data: every step reads the configured local roots and the PostgreSQL control
plane. Acquisition and ingest are separate, rights-gated steps (see `README.md`,
`DATA_SOURCES.md`).

## 0. Prerequisites

| requirement | check |
| --- | --- |
| CPython 3.12, `uv`, Node.js 24, pnpm 11 | `uv --version`, `node --version`, `pnpm --version` |
| `.env` with `DYNAMIS_DATASET_ROOT`, `DYNAMIS_DATABASE_ROOT`, `POSTGRES_URL` | see `.env.example` |
| PostgreSQL 18.6 running and migrated | `docker compose up -d postgres` · `uv run alembic upgrade head` |
| Accepted local sources ingested (registered Silver) | DFL/Sportec IDSSE `DFL-MAT-J03WPY` (2 tracking periods + events); SkillCorner Open Data `1925299` (2 tracking + 2 body-pose periods) |
| A committed working tree | processor runs record the HEAD revision; `dynamis-demo-prepare` refuses uncommitted processor code unless `--allow-dirty` |

```bash
uv sync --locked
pnpm install --frozen-lockfile
```

## 1. Check readiness (read-only)

```bash
uv run dynamis-demo-prepare --check
```

`--check` verifies that every required stream is registered and present on disk, then verifies
what the API will serve. It exits:

| exit | meaning |
| --- | --- |
| `0` | READY — every check passed; flagship URLs are printed |
| `1` | NOT READY — a `FAIL` line names each missing artifact or stale serving state |
| `2` | PREPARATION FAILED — a required accepted local source is missing; ingest it first |

Checks performed:

- Gold serves exactly the control plane's current revisions per dataset;
- per tracking stream, the served tactical series for every level the capability matrix
  (`sources/tactical-capability-matrix.json`) declares supported — DFL A/B/C/D, SkillCorner A/B/C;
- locomotor metrics exist only for athletes (no ball or other non-player object);
- a current Pose kinematics run exists for each SkillCorner pose period.

A receipt is written to `${DYNAMIS_DATASET_ROOT}/cache/receipts/dynamis-demo/preparation/`.

## 2. Prepare (materialize what is missing)

```bash
uv run dynamis-demo-prepare
```

For each flagship session it materializes, in order, and skips a stream whose current completed
run already has the same algorithm, parameters hash and input checksums:

1. athlete-only locomotor metrics per tracking period (`locomotor.speed_effort_kinematics`,
   `entity_object_types = ["player"]`);
2. Pose translation-invariant kinematics per SkillCorner pose period;
3. tactical Level A geometry, Level B clipped territory, Level C arrival-time influence
   (MODEL_ESTIMATED), Level D source-event snapshots where supported, and source-authorized
   MatchLab V3 per tracking period;
4. Gold export → dbt build → publish when served metrics disagree with the control plane;
5. the same verification as `--check`, then the flagship URLs.

Reference timings on the reference workstation (first run): DFL per period — A ≈ 1.5 min,
B ≈ 3 min, C ≈ 17 min, D < 1.5 min; SkillCorner per period — C ≈ 9.5 min; locomotor and Pose
< 1 min each. Reruns with unchanged inputs and parameters are no-ops.

Options:

| flag | effect |
| --- | --- |
| `--force` | rerun every processor even when a current run exists (after processor code changes that do not change parameters) |
| `--skip-level C` | do not materialize a level (repeatable); verification still reports it, so the result is NOT READY |
| `--allow-dirty` | persist runs from a working tree with uncommitted processor code (development only) |
| `--base-url URL` | base for printed URLs (default `http://127.0.0.1:5173`) |

## 3. Start the product

```bash
uv run dynamis-serve            # API on :8000
pnpm --filter @dynamis/web run dev   # workbench on :5173 (proxies /api to :8000)
```

## 4. Flagship routes

| route | what must be visible |
| --- | --- |
| `/lab/skillcorner-opendata/1925299?view=matchlab&stream=tracking-period-1&subject=11897&t_ns=120000000000` | Tactical Map left, genuine selected-player Pose 3D centre, persistent Analysis Dashboard right; one canonical player/time context, one shared transport, and explicit source/method/measurement-class provenance. The route stays at 48/30/22 at 1600×1000 and 1440×900, and keeps all three panels visible at 1366×768. |
| `/lab/dfl-sportec-idsse/DFL-MAT-J03WPY?view=matchlab&stream=tracking-period-1&t_ns=300020000000` | Real DFL Tactical Map and tactical Analysis Dashboard, with an explicit Pose-unavailable state because this period has no registered Pose source. |
| `/catalog` | five datasets with laboratory chips and rights |
| `/lab/dfl-sportec-idsse/DFL-MAT-J03WPY?view=overview` | athlete locomotor headline (no ball), charts, derived metrics |
| `/lab/dfl-sportec-idsse/DFL-MAT-J03WPY?view=field&stream=tracking-period-1&tactical=live` | Tactical Map default with a fitted orthographic pitch at 00:00:01.020, source possession/ball context and GK/DEF/MID/ATT inter-line structure; optional Occupied area; Space territory + MODEL_ESTIMATED influence; DFL source-event snapshots with seek. Structure Lift is optional and exposes declared scalar elevation with a restrained pitch shadow. |
| `/lab/skillcorner-opendata/1925299?view=field&stream=tracking-period-1&tactical=live` | Tactical Map default with a fitted orthographic pitch at 00:00:00.000, source-declared possession/direction and GK/DEF/MID/ATT structure; local relations on demand; no provider event/phase labels. Structure Lift is an optional orthographic view. |
| `/lab/skillcorner-opendata/1925299?view=pose&stream=pose-period-1` | body-local skeleton of the first subject at its first observation; subject selector with shirt/name; all-subject world with focus ring |
| `/compare`, `/methods`, `/quality`, `/runs` | method, provenance, quality/rights and run evidence |

Opening a Field or Pose route without `t_ns` lands on the stream's first canonical frame (Pose:
the subject's first observation). The transport timeline seeks within the stream's canonical span.

## 5. Real-data browser acceptance

With the API and workbench running:

```bash
DYNAMIS_REAL_BASE_URL=http://127.0.0.1:5173 pnpm --filter @dynamis/web run test:e2e:real
```

The suite (`apps/web/e2e-real/`) intercepts nothing. It fails on any console error, page error or
API 5xx on a flagship path (the only tolerated messages are listed in
`docs/audits/field-pose-system/ACCEPTANCE-MATRIX.md`). The fixture suite
(`pnpm run web:e2e`) remains the deterministic, data-free contract.

## 6. Troubleshooting

| symptom | cause | action |
| --- | --- | --- |
| Tactical tab says **Not materialized** | the level is supported but no processor output is registered | `uv run dynamis-demo-prepare` |
| Tactical tab says **Unsupported by this source** | the capability matrix declares the level unavailable for the source | expected; the reason is shown |
| Overview headline names the ball | Gold predates the athlete-only locomotor revision | `uv run dynamis-demo-prepare` (refreshes Gold) |
| `PREPARATION FAILED … absent` | a registered Silver artifact is missing on disk | restore the accepted local corpus / rerun ingest |
| `uncommitted changes …` | processor code differs from HEAD | commit, or `--allow-dirty` for a development run |
| `uv sync` cannot replace `dynamis-serve.exe` (Windows) | a running API holds the script executable | stop the API, or run it as `uv run --no-sync python -m dynamis.serving.cli` |
