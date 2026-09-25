# ADR-003: Prepare MatchLab frames in the existing Arrow/Comlink worker

Status: accepted for implementation.

## Context

The app already decodes Arrow in a Comlink Web Worker and transfers typed buffers. Field frame grouping, tactical polygon parsing and Pose frame extraction currently perform substantial preparation on the main thread.

## Decision

Extend the existing worker boundary to prepare tracking, Pose, tactical geometry and scalar-grid buffers from bounded Arrow windows. Transfer canonical BigInt time, identity indexes/dictionaries, source availability masks, positions, errors and geometry offsets in typed arrays. Keep request ownership in TanStack Query and PlaybackChunkCoordinator. Keep Three buffer mutation and interaction on the main thread.

Do not add another worker framework, materialize a whole session, or build row-object maps at animation-frame cadence. The worker performs structural preparation only; scientific calculations remain in their accepted processors.

## Consequences

Query/cache boundaries and exact source windows remain unchanged. Source row identity, canonical time, unit, measurement class, coordinate frame and quality metadata travel with prepared buffers. Missing rows remain missing.

