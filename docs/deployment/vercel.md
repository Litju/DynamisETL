# Vercel deployment

## Target topology

One Vercel project, `dynamisdata`, builds the FastAPI `app` service and React/Vite `web` service from this repository. The app runs as a Vercel Python Function on Fluid Compute. Neon Postgres and Vercel Private Blob are provisioned through Vercel and accessed only by the app service.

The root [`vercel.json`](../../vercel.json) routes `/api` and `/api/*` to `app`; all other paths route to `web`. This keeps browser API calls same-origin and lets the Vite app own deep links. Preview and Production use separate Neon endpoints. The immutable Blob keys include the artifact SHA-256, and upload/read checks compare the stored bytes with that digest.

There are no internal service bindings: the static Vite service has no server-side runtime, and FastAPI does not call the Vite service. The browser calls the public same-origin `/api` routes. Neon and Blob are Vercel-managed storage integrations, not Vercel services.

## Environment contract

Connect separate Neon resources to the Preview and Production environments in the Vercel project. The app reads the pooled URL from `POSTGRES_URL` or the Neon `DATABASE_URL` alias; Alembic uses `DYNAMIS_MIGRATION_POSTGRES_URL` or Neon `DATABASE_URL_UNPOOLED`. The Vercel Blob integration supplies `BLOB_READ_WRITE_TOKEN`; do not add it to a `VITE_*` variable or source file.

Set `DYNAMIS_ENVIRONMENT` to `preview` and `production` in the matching Vercel environments, and set `DYNAMIS_OBJECT_STORE_PROVIDER=vercel-blob`. Public serving defaults to rights enforcement. The app uses an ephemeral `/tmp` root for local-only cache/config paths in Vercel Functions.

## Release order

1. Provision the `dynamisdata` project and attach a private Blob store.
2. Attach an isolated Neon resource to Preview; keep Production on its separate Neon endpoint.
3. Deploy a Preview from the local branch. No Git push is needed.
4. Run `uv run python infra/deploy/migrate.py --apply`, then seed the pinned allowlist with `uv run python infra/deploy/seed.py --apply --artifact-dataset-id <allowlisted-dataset-id> --artifact-checksum-sha256 <sha256>`. Preview uploads exactly that one checksum-matched Parquet object; restricted sources are excluded. Production reuses the dataset and checksum in the accepted Preview receipt.
5. Run `pnpm --filter @dynamis/web run test:e2e:preview` with `DYNAMIS_REAL_BASE_URL`, `DYNAMIS_PREVIEW_ARTIFACT_RECEIPT`, `DYNAMIS_PREVIEW_SMOKE_RECEIPT`, and `DYNAMIS_CODE_GIT_SHA` set. It checks health/readiness, Neon-backed rights-filtered reads, the one private Parquet object, same-origin API calls, deep-link reload, local-address leakage, and client-side secret leakage.
6. Run `uv run python infra/deploy/record_preview_release.py --preview-url <url> --artifact-receipt <path> --smoke-receipt <path>`. It rechecks Alembic heads and Gold tables, verifies the artifact receipt, and records the Neon endpoint fingerprint. Production migration and seed both require this evidence, a different Neon endpoint fingerprint, and matching Preview/Production artifact checksums.
7. Only after every Preview gate passes, deploy the same local revision to Production with Production environment values.

Vercel runtime logs and Observability are the runtime diagnostics for both environments.
