# V4 multi-sport architecture

Status: frozen. Machine authority: [`architecture/system-v4.json`](../../../architecture/system-v4.json) and its JSON Schema. V4 adds a sports semantic and catalog overlay to the accepted scientific core; it does not replace that core.

## Authorities

`Dataset`, `Session`, `Trial`, `Stream`, `Artifact`, `Run`, `Metric`, provenance, quality and rights remain canonical. Bronze/Silver/Gold remain immutable. PostgreSQL owns semantic, catalog, provenance and Gold metadata; Parquet/Arrow in private object storage owns dense artifacts; DuckDB/PyArrow remain the read plane. AlgorithmSpec, parameters hash, code SHA and input checksums continue to identify deterministic work. MatchFrameContext and existing lab state ownership are unchanged.

The overlay adds `Sport`, `Competition`, `CompetitionEdition`, `Team`, `Contest`, `ContestTeam`, `ContestPeriod`, `TeamRosterMembership` and `SessionSportContext`. A Session is not automatically a Contest. A session gets a sports link only when accepted source facts support one. Athlete identity remains the existing dataset-scoped Subject identity.

Provider IDs are aliases in a versioned crosswalk. Display names cannot merge entities. Candidate matching may suggest a mapping, but a deterministic key or explicit mapping authority must accept it.

## Data and products

Every V4 canonical or derived analytical product declares one versioned data grain and exact axes. Duplicate complete axis keys fail publication. Existing products without a defensible grain stay unannotated until migrated. Catalog discovery remains metadata-only. `CapabilityProfile` reports upstream, registered and materialized evidence separately, records its origin, and retains `MODEL_ESTIMATED`; deterministic product routes consume the materialized profile and available grains.

Cross-sport events retain source event type and validate provider/sport attributes against a versioned schema. Spatial metadata names the actual surface and preserves reversible source transforms. Clock mappings declare how source time reaches canonical session/contest nanoseconds. No renderer or UI owns those scientific conversions.

Dense Parquet files follow natural grain boundaries and keep row-group statistics for projection and predicate pushdown. PostgreSQL never stores dense telemetry. OpenLineage is an export mapping only. V4 starts with Parquet; Iceberg and Delta are explicitly deferred under [ADR-003](ADR-003-parquet-no-table-format.md).

## Scope boundary

RES-119 freezes and implements this contract only. SportsDataverse integration, more SkillCorner releases, season/game/navigation products, basketball tracking ingestion, new providers and UI are later work. Existing football and basketball source facts may be backfilled where authoritative. White CMJ and GymAware remain valid scientific/laboratory data without sport, competition or contest records.
