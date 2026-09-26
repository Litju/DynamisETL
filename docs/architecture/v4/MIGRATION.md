# V4 implementation and migration

Entry: protected `main`, commit `05419cf9b40b4853500c893b068c581826de3de2`. Work in one worktree and keep one atomic commit per architecture or database-migration unit.

1. Freeze and validate `system-v4.json`, its schema, this document set and the ADRs.
2. Additive PostgreSQL tables represent the semantic overlay, source catalog, provider crosswalk and spatial/clock authority. Grain metadata on existing stream/artifact rows is nullable so preserved legacy records survive; accepted streams are backfilled when their exact axes are established.
3. Backfill only facts already present in the registered source/domain data. Reuse Subject IDs. Attach sport only when the source declares it; never force CMJ or GymAware into a contest.
4. Source registration synchronizes metadata-only catalog entries. Acquisition/materialization still uses the existing deterministic and rights-gated path.
5. Validate grain, derive capability profiles, route products and export lineage with deterministic contracts. Do not build downstream labs or UI here.
6. Run the full upgrade/downgrade/replay/drift migration lifecycle and current Python, web, MatchLab and laboratory regressions.

The migration is additive and does not rewrite scientific sample rows or alter existing entity identity. Downgrade removes only V4 structures and nullable V4 grain annotations; it does not modify legacy values. Current run checksums, quality, rights, provenance and MatchFrameContext remain authoritative.
