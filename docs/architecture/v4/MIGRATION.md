# V4 implementation and migration

Entry: protected `main`, commit `05419cf9b40b4853500c893b068c581826de3de2`. Work in one worktree and keep one atomic commit per architecture or database-migration unit.

1. Freeze and validate `system-v4.json`, its schema, this document set and the ADRs.
2. Additive PostgreSQL tables represent the semantic overlay, source catalog, provider crosswalk and spatial/clock authority. Grain metadata on existing stream/artifact rows is nullable so preserved legacy records survive; accepted streams are backfilled when their exact axes are established.
3. Backfill only facts already present in the registered source/domain data. Reuse Subject IDs. Attach sport only when the source declares it; never force CMJ or GymAware into a contest.
4. Source registration synchronizes metadata-only catalog entries. Acquisition/materialization still uses the existing deterministic and rights-gated path.
5. Validate grain, derive capability profiles, route products and export lineage with deterministic contracts. Do not build downstream labs or UI here.
6. Run the full upgrade/downgrade/replay/drift migration lifecycle and current Python, web, MatchLab and laboratory regressions.

The migration is additive and does not rewrite scientific sample rows or alter existing entity identity. Downgrade removes only V4 structures and nullable V4 grain annotations; it does not modify legacy values. Current run checksums, quality, rights, provenance and MatchFrameContext remain authoritative.

## MatchLab dense-read regression

`benchmarks/architecture_v2/benchmark_backend.py --mode both --iterations 20` ran at implementation commit `107f070`. The current dense service remained below the published V2 p95 baselines on all five local workloads: White CMJ 62.65 ms (64.14), GNSS 137.06 ms (218.40), DFL tracking 80.46 ms (100.39), SkillCorner Pose 148.12 ms (198.30), and maximum allowed window 1,018.00 ms (1,129.47). The receipt is outside Git. On the maximum-window case the PyArrow reduced candidate was not semantically equivalent to the current service, so its timing is not accepted as a replacement result.
