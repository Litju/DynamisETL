# ADR-002: separate upstream catalog from materialized sessions

Status: accepted for V4.

`SourceCatalogEntry` is a metadata-only record for a declared upstream contest, dataset, release asset or aggregate. Availability tracks upstream, registered, acquired, materialized and ready states, with separate failure states. Upstream availability is not a Session and catalog browsing performs no dense acquisition.

The distinction makes discovery cheap and rights-aware while preserving current checksum-gated deterministic promotion into Bronze and the existing artifact/provenance path.
