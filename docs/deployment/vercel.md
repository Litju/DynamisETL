# Vercel deployment

## Target topology

One Vercel project, `dynamisdata`, builds the FastAPI `app` service and React/Vite `web` service from this repository. The app runs as a Vercel Python Function on Fluid Compute. Neon Postgres and Vercel Private Blob are provisioned through Vercel and accessed only by the app service.

The root [`vercel.json`](../../vercel.json) routes `/api` and `/api/*` to `app`; all other paths route to `web`. This keeps browser API calls same-origin and lets the Vite app own deep links. Preview and Production use separate Neon endpoints. The immutable Blob keys include the artifact SHA-256, and each release stores a private manifest at `manifests/<environment>/<git-sha>.json`. A World route is ready only when every sample and processing artifact required by its resource appears in that exact manifest. Unmanifested artifact reads return `404`.

There are no internal service bindings: the static Vite service has no server-side runtime, and FastAPI does not call the Vite service. The browser calls the public same-origin `/api` routes. Neon and Blob are Vercel-managed storage integrations, not Vercel services.

## Environment contract

Connect separate Neon resources to the Preview and Production environments in the Vercel project. The app reads the pooled URL from `POSTGRES_URL` or the Neon `DATABASE_URL` alias; Alembic uses `DYNAMIS_MIGRATION_POSTGRES_URL` or Neon `DATABASE_URL_UNPOOLED`. The Vercel Blob integration supplies `BLOB_READ_WRITE_TOKEN`; do not add it to a `VITE_*` variable or source file.

Set `DYNAMIS_ENVIRONMENT` to `preview` and `production` in the matching Vercel environments, set `DYNAMIS_OBJECT_STORE_PROVIDER=vercel-blob`, and set `DYNAMIS_DATABASE_NAME=dynamis_sample`. That name selects a clean database inside each existing Neon branch; the release does not clone the existing databases or their unselected sessions. Public serving defaults to rights enforcement. The app uses an ephemeral `/tmp` root for local-only cache/config paths in Vercel Functions.

The Git integration continues to create Preview deployments for feature branches. Automatic deployment of `main` is disabled in `vercel.json`; Production is deployed manually only after the merged-SHA Neon and Blob promotion receipt passes.

## Curated public slice

The sample manifest exposes exactly one selected resource per public dataset: DFL `DFL-MAT-J03WPY` (GameLab and MatchLab), SkillCorner football `2011166` (MatchLab), Basketball `114243` (MatchLab), and White CMJ `white-s002` (PerformanceLab). Private Blob receives only the session-linked sample Parquet files required for those World routes; optional processing artifacts are not published. White CMJ ingestion filters the source NPZ to `white-s002`; the complete source corpus stays local. Other registered resources remain metadata-only and have no openable World route until their complete bytes are added to a release manifest.

## Release order

1. Open the feature PR and wait for its Vercel Preview deployment.
2. Create an empty `dynamis_sample` database in the Preview Neon branch and set `DYNAMIS_DATABASE_NAME=dynamis_sample` with the Preview Neon pooled/direct URLs and Preview Blob token. Point `DYNAMIS_DATASET_ROOT` at a staging root containing only the Bronze keys in the sample allow-list, then run `uv run python infra/deploy/migrate.py --apply` and `uv run python infra/deploy/seed.py --apply`. The seed ingests only the four selected sessions and writes a private SHA-scoped Blob manifest for their sample artifacts.
3. Run `pnpm --filter @dynamis/web run test:e2e:preview` with `DYNAMIS_REAL_BASE_URL`, `DYNAMIS_PREVIEW_ARTIFACT_RECEIPT`, `DYNAMIS_PREVIEW_SMOKE_RECEIPT`, and `DYNAMIS_CODE_GIT_SHA`. It checks rights, same-origin calls, a manifest-backed dense read, the curated World route, and that no other catalog route reports ready without its complete Blob set.
4. Run `uv run python infra/deploy/record_preview_release.py --preview-url <url> --artifact-receipt <path> --smoke-receipt <path>`. It rechecks the Alembic head, sample artifact manifest, browser smoke, rights, and Preview Neon endpoint fingerprint. Season Gold marts are not required for these four Worlds.
5. Run protected CI and CodeRabbit, address concrete findings, then merge the PR. `main` does not auto-deploy to Production.
6. Create an empty `dynamis_sample` database in the Production Neon branch and set `DYNAMIS_DATABASE_NAME=dynamis_sample` there. From the merged `main` SHA, deploy a Preview with Preview environment values, repeat seed and smoke, and record merged-SHA Preview evidence. Set the Production Blob token and run `DYNAMIS_DEPLOY_ENV=production uv run python infra/deploy/upload_artifacts.py --apply --receipt <production.json>`; the production manifest must match the Preview object set.
7. Set `DYNAMIS_DEPLOY_ENV=production`, `DYNAMIS_CODE_GIT_SHA` to the merged SHA, both direct Neon URLs, both Neon project/branch IDs, the merged-SHA Preview release evidence, and both Blob receipts. Run `uv run python -m infra.deploy.promote_neon --check --preview-blob-receipt <preview.json> --production-blob-receipt <production.json>`, review the preflight, then run the same command with `--apply`. It writes a receipt with both Neon project/branch IDs, Git SHA, Alembic head, `pg_dump` SHA-256, table/row/Gold counts, rights allow-list hash, and Blob receipt parity.
8. Verify that Production Neon counts/head and the Production Blob manifest match the merged `main` SHA and promotion receipt. Only then deploy `main` with Production environment values and run final public acceptance.

Vercel runtime logs and Observability are the runtime diagnostics for both environments.
