/**
 * TanStack Query bindings.
 *
 * Query owns server state (catalog, explorer, metrics, provenance, quality,
 * rights, dense windows). Nothing here is copied into Zustand: transient
 * playback/hover state lives in the analysis store instead.
 */

import { queryOptions } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

export interface MetricQuery {
  readonly datasetId?: string | undefined;
  readonly sessionId?: string | undefined;
  readonly subjectId?: string | undefined;
  readonly trialId?: string | undefined;
  readonly streamId?: string | undefined;
  readonly metricId?: string | undefined;
  readonly entityId?: string | undefined;
  readonly limit?: number | undefined;
  readonly offset?: number | undefined;
}

export interface WindowQuery {
  readonly artifactId: string;
  readonly fromNs?: number | undefined;
  readonly toNs?: number | undefined;
  readonly columns?: readonly string[] | undefined;
  readonly maxPoints?: number | undefined;
  /**
   * Scope the window to one tracked entity. A dense artifact interleaves every
   * entity on the same time axis, so a viewer that renders one player or one
   * subject must say so or pay for every other entity's rows.
   */
  readonly entityId?: string | undefined;
  readonly cacheScope?: "dense-window" | "dense-chunk" | undefined;
  readonly chunkId?: string | undefined;
}

export interface TacticalArtifactQuery {
  readonly datasetId: string;
  readonly sessionId?: string | undefined;
  readonly streamId?: string | undefined;
  readonly seriesName?: string | undefined;
}

export interface ProcessingArtifactQuery {
  readonly datasetId: string;
  readonly sessionId?: string | undefined;
  readonly streamId?: string | undefined;
  readonly algorithmId?: string | undefined;
  readonly seriesName?: string | undefined;
}

export interface PoseRangeReportQuery {
  readonly datasetId: string;
  readonly sessionId: string;
  readonly streamId: string;
  readonly subjectId: string;
  readonly fromNs: number;
  readonly toNs: number;
  readonly landmarkName: string;
}

export interface TacticalSeriesQuery {
  readonly artifactId: string;
  readonly fromNs?: number | undefined;
  readonly toNs?: number | undefined;
  readonly maxPoints?: number | undefined;
  /** Column projection; overlays read only what they draw. */
  readonly columns?: readonly string[] | undefined;
}

function compact(params: Record<string, string | number | undefined>): Record<string, string> {
  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      output[key] = String(value);
    }
  }
  return output;
}

export const queryKeys = {
  status: ["serving", "status"] as const,
  datasets: ["catalog", "datasets"] as const,
  sportsMatches: ["catalog", "sports", "matches"] as const,
  dataset: (datasetId: string) => ["catalog", "datasets", datasetId] as const,
  sessions: (datasetId: string) => ["catalog", "datasets", datasetId, "sessions"] as const,
  session: (datasetId: string, sessionId: string) =>
    ["catalog", "datasets", datasetId, "sessions", sessionId] as const,
  metrics: (query: MetricQuery) => ["metrics", query] as const,
  metricDefinitions: ["metrics", "definitions"] as const,
  methodology: (metricId: string) => ["metrics", "methodology", metricId] as const,
  provenance: (derivedMetricId: string) =>
    ["derived-metrics", derivedMetricId, "provenance"] as const,
  quality: (query: Record<string, string | undefined>) => ["quality", query] as const,
  runs: (query: Record<string, string | undefined>) => ["runs", query] as const,
  rights: ["rights"] as const,
  artifact: (artifactId: string) => ["artifacts", artifactId] as const,
  window: (query: WindowQuery) => [
    query.cacheScope ?? "dense-window",
    query.artifactId,
    "window",
    query.chunkId ?? "single",
    query.fromNs ?? null,
    query.toNs ?? null,
    query.columns?.join(",") ?? null,
    query.maxPoints ?? null,
    query.entityId ?? null,
  ] as const,
  tacticalCapabilities: (datasetId: string) => ["tactical", "capabilities", datasetId] as const,
  tacticalQuality: (datasetId: string) => ["tactical", "quality", datasetId] as const,
  tacticalMethodology: ["tactical", "methodology"] as const,
  tacticalArtifacts: (query: TacticalArtifactQuery) => ["tactical", "artifacts", query] as const,
  processingArtifacts: (query: ProcessingArtifactQuery) => ["processing", "artifacts", query] as const,
  poseRangeReport: (query: PoseRangeReportQuery) => ["pose", "range-report", query] as const,
  tacticalSeries: (query: TacticalSeriesQuery) => ["tactical", "series", query] as const,
};

export const servingStatusQuery = () =>
  queryOptions({
    queryKey: queryKeys.status,
    queryFn: async () => unwrap(await api.GET("/api/serving/status")),
    staleTime: 30_000,
  });

export const datasetsQuery = () =>
  queryOptions({
    queryKey: queryKeys.datasets,
    queryFn: async () => unwrap(await api.GET("/api/catalog/datasets")),
    staleTime: 30_000,
  });

export const sportsCatalogMatchesQuery = () =>
  queryOptions({
    queryKey: queryKeys.sportsMatches,
    queryFn: async () => unwrap(await api.GET("/api/catalog/sports/matches")),
    staleTime: 30_000,
  });

export const sourceCapabilitiesQuery = (datasetId: string) =>
  queryOptions({
    queryKey: ["catalog", "source-capabilities", datasetId] as const,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/catalog/source-capabilities", {
          params: { query: { dataset_id: datasetId } },
        }),
      ),
    staleTime: 30_000,
  });

export const datasetQuery = (datasetId: string) =>
  queryOptions({
    queryKey: queryKeys.dataset(datasetId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/catalog/datasets/{dataset_id}", {
          params: { path: { dataset_id: datasetId } },
        }),
      ),
    staleTime: 30_000,
  });

export const sessionsQuery = (datasetId: string) =>
  queryOptions({
    queryKey: queryKeys.sessions(datasetId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/catalog/datasets/{dataset_id}/sessions", {
          params: { path: { dataset_id: datasetId } },
        }),
      ),
    staleTime: 30_000,
  });

export const sessionQuery = (datasetId: string, sessionId: string) =>
  queryOptions({
    queryKey: queryKeys.session(datasetId, sessionId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/catalog/datasets/{dataset_id}/sessions/{session_id}", {
          params: { path: { dataset_id: datasetId, session_id: sessionId } },
        }),
      ),
    staleTime: 30_000,
  });

export const metricsQuery = (query: MetricQuery) =>
  queryOptions({
    queryKey: queryKeys.metrics(query),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/metrics", {
          params: {
            query: compact({
              dataset_id: query.datasetId,
              session_id: query.sessionId,
              subject_id: query.subjectId,
              trial_id: query.trialId,
              stream_id: query.streamId,
              metric_id: query.metricId,
              entity_id: query.entityId,
              limit: query.limit,
              offset: query.offset,
            }),
          },
        }),
      ),
    staleTime: 15_000,
  });

/** The registered metric vocabulary, for discovery and comparison selection. */
export const metricDefinitionsQuery = () =>
  queryOptions({
    queryKey: queryKeys.metricDefinitions,
    queryFn: async () => unwrap(await api.GET("/api/metrics/definitions")),
    staleTime: 5 * 60_000,
  });

export const methodologyQuery = (metricId: string) =>
  queryOptions({
    queryKey: queryKeys.methodology(metricId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/metrics/methodology/{metric_id}", {
          params: { path: { metric_id: metricId } },
        }),
      ),
    staleTime: 60_000,
  });

export const provenanceQuery = (derivedMetricId: string) =>
  queryOptions({
    queryKey: queryKeys.provenance(derivedMetricId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/derived-metrics/{derived_metric_id}/provenance", {
          params: { path: { derived_metric_id: derivedMetricId } },
        }),
      ),
  });

export const qualityQuery = (query: {
  datasetId?: string | undefined;
  sessionId?: string | undefined;
  severity?: "INFO" | "WARNING" | "ERROR" | undefined;
  limit?: number | undefined;
  offset?: number | undefined;
}) =>
  queryOptions({
    queryKey: queryKeys.quality({
      datasetId: query.datasetId,
      sessionId: query.sessionId,
      severity: query.severity,
      limit: query.limit?.toString(),
      offset: query.offset?.toString(),
    }),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/quality", {
          params: {
            query: compact({
              dataset_id: query.datasetId,
              session_id: query.sessionId,
              severity: query.severity,
              limit: query.limit,
              offset: query.offset,
            }),
          },
        }),
      ),
    staleTime: 15_000,
  });

export const runsQuery = (query: { datasetId?: string | undefined; limit?: number | undefined; offset?: number | undefined }) =>
  queryOptions({
    queryKey: queryKeys.runs({
      datasetId: query.datasetId,
      limit: query.limit?.toString(),
      offset: query.offset?.toString(),
    }),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/runs", {
          params: {
            query: compact({
              dataset_id: query.datasetId,
              limit: query.limit,
              offset: query.offset,
            }),
          },
        }),
      ),
    staleTime: 15_000,
  });

export const rightsQuery = () =>
  queryOptions({
    queryKey: queryKeys.rights,
    queryFn: async () => unwrap(await api.GET("/api/rights")),
    staleTime: 60_000,
  });

export const artifactQuery = (artifactId: string) =>
  queryOptions({
    queryKey: queryKeys.artifact(artifactId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/artifacts/{artifact_id}", {
          params: { path: { artifact_id: artifactId } },
        }),
      ),
    staleTime: 60_000,
  });

export const windowQuery = (query: WindowQuery) =>
  queryOptions({
    queryKey: queryKeys.window(query),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/artifacts/{artifact_id}/window", {
          params: {
            path: { artifact_id: query.artifactId },
            query: compact({
              from_ns: query.fromNs,
              to_ns: query.toNs,
              columns: query.columns?.join(","),
              max_points: query.maxPoints,
              entity_id: query.entityId,
            }),
          },
          signal,
        }),
      ),
    staleTime: 30_000,
  });

export const tacticalCapabilitiesQuery = (datasetId: string) =>
  queryOptions({
    queryKey: queryKeys.tacticalCapabilities(datasetId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/tactical/capabilities/{dataset_id}", {
          params: { path: { dataset_id: datasetId } },
        }),
      ),
    staleTime: 5 * 60_000,
  });

export const tacticalQualityQuery = (datasetId: string) =>
  queryOptions({
    queryKey: queryKeys.tacticalQuality(datasetId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/tactical/quality/{dataset_id}", {
          params: { path: { dataset_id: datasetId } },
        }),
      ),
    staleTime: 30_000,
  });

export const tacticalMethodologyQuery = () =>
  queryOptions({
    queryKey: queryKeys.tacticalMethodology,
    queryFn: async () => unwrap(await api.GET("/api/tactical/methodology")),
    staleTime: 5 * 60_000,
  });

export const tacticalArtifactsQuery = (query: TacticalArtifactQuery) =>
  queryOptions({
    queryKey: queryKeys.tacticalArtifacts(query),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/tactical/artifacts", {
          params: {
            query: {
              dataset_id: query.datasetId,
              ...compact({
                session_id: query.sessionId,
                stream_id: query.streamId,
                series_name: query.seriesName,
              }),
            },
          },
        }),
      ),
    staleTime: 30_000,
  });

export const processingArtifactsQuery = (query: ProcessingArtifactQuery) =>
  queryOptions({
    queryKey: queryKeys.processingArtifacts(query),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/processing/artifacts", {
          params: {
            query: {
              dataset_id: query.datasetId,
              ...compact({
              session_id: query.sessionId,
              stream_id: query.streamId,
              algorithm_id: query.algorithmId,
              series_name: query.seriesName,
              }),
            },
          },
        }),
      ),
    staleTime: 30_000,
  });

export const poseRangeReportQuery = (query: PoseRangeReportQuery) =>
  queryOptions({
    queryKey: queryKeys.poseRangeReport(query),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/pose/range-report", {
          params: {
            query: {
              dataset_id: query.datasetId,
              session_id: query.sessionId,
              stream_id: query.streamId,
              subject_id: query.subjectId,
              from_ns: query.fromNs,
              to_ns: query.toNs,
              landmark_name: query.landmarkName,
            },
          },
        }),
      ),
    staleTime: 30_000,
  });

export const tacticalSeriesQuery = (query: TacticalSeriesQuery) =>
  queryOptions({
    queryKey: queryKeys.tacticalSeries(query),
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/tactical/series/{artifact_id}", {
          params: {
            path: { artifact_id: query.artifactId },
            query: compact({
              from_ns: query.fromNs,
              to_ns: query.toNs,
              max_points: query.maxPoints,
              columns: query.columns?.join(","),
            }),
          },
          signal,
        }),
      ),
    // A processing artifact id names immutable content (a rerun gets a new
    // run/artifact identity), so a served window never goes stale.
    staleTime: Number.POSITIVE_INFINITY,
  });

// -- SeasonLab ------------------------------------------------------------------
// Season metadata (editions, family registry/facets) is small and cached long;
// value queries are always bounded by family, population and projected metrics.

export interface SeasonRowsQuery {
  readonly editionId: string;
  readonly family: string;
  readonly metrics: readonly string[];
  readonly teamId?: string | undefined;
  readonly positionGroup?: string | undefined;
  readonly subjectIds?: readonly string[] | undefined;
  readonly minMatches?: number | undefined;
  readonly limit?: number | undefined;
}

export interface SeasonProfileQuery {
  readonly editionId: string;
  readonly family: string;
  readonly subjectId: string;
  readonly teamId?: string | undefined;
  readonly positionGroup?: string | undefined;
  readonly population: "edition" | "position" | "team";
  readonly minMatches?: number | undefined;
  readonly metrics: readonly string[];
  readonly populationTeamId?: string | undefined;
  readonly populationPositionGroup?: string | undefined;
}

export const seasonEditionsQuery = () =>
  queryOptions({
    queryKey: ["season", "editions"] as const,
    queryFn: async () => unwrap(await api.GET("/api/season/editions")),
    staleTime: 5 * 60_000,
  });

export const seasonFamilyQuery = (editionId: string, family: string) =>
  queryOptions({
    queryKey: ["season", "family", editionId, family] as const,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/season/editions/{edition_id}/families/{family}", {
          params: { path: { edition_id: editionId, family } },
        }),
      ),
    staleTime: 5 * 60_000,
  });

export const seasonRowsQuery = (query: SeasonRowsQuery) =>
  queryOptions({
    queryKey: ["season", "rows", query] as const,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/season/editions/{edition_id}/families/{family}/rows", {
          params: {
            path: { edition_id: query.editionId, family: query.family },
            query: {
              metrics: query.metrics.join(",") || null,
              team_id: query.teamId ?? null,
              position_group: query.positionGroup ?? null,
              subject_id: query.subjectIds ? [...query.subjectIds] : null,
              min_matches: query.minMatches ?? null,
              limit: query.limit ?? 1000,
            },
          },
          signal,
        }),
      ),
    staleTime: 5 * 60_000,
  });

export const seasonProfileQuery = (query: SeasonProfileQuery) =>
  queryOptions({
    queryKey: ["season", "profile", query] as const,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/season/editions/{edition_id}/families/{family}/profile", {
          params: {
            path: { edition_id: query.editionId, family: query.family },
            query: {
              subject_id: query.subjectId,
              team_id: query.teamId ?? null,
              position_group: query.positionGroup ?? null,
              population: query.population,
              min_matches: query.minMatches ?? null,
              metrics: query.metrics.join(",") || null,
              population_team_id: query.populationTeamId ?? null,
              population_position_group: query.populationPositionGroup ?? null,
            },
          },
          signal,
        }),
      ),
    staleTime: 5 * 60_000,
  });

export const seasonLinksQuery = (editionId: string, subjectId: string) =>
  queryOptions({
    queryKey: ["season", "links", editionId, subjectId] as const,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/season/editions/{edition_id}/links", {
          params: { path: { edition_id: editionId }, query: { subject_id: subjectId } },
        }),
      ),
    staleTime: 5 * 60_000,
  });

// -- GameLab --------------------------------------------------------------------
// Game metadata is small; one game's full play-by-play (≤ ~650 plays) is one
// bounded request, keyed by contest so a game switch never shows another game.

export const gameEditionsQuery = () =>
  queryOptions({
    queryKey: ["games", "editions"] as const,
    queryFn: async () => unwrap(await api.GET("/api/games/editions")),
    staleTime: 5 * 60_000,
  });

export const gamesQuery = (editionId: string, offset: number) =>
  queryOptions({
    queryKey: ["games", "list", editionId, offset] as const,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/games", {
          params: { query: { edition_id: editionId, limit: 60, offset } },
          signal,
        }),
      ),
    staleTime: 5 * 60_000,
  });

export const gameQuery = (contestId: string) =>
  queryOptions({
    queryKey: ["games", "detail", contestId] as const,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/games/{contest_id}", {
          params: { path: { contest_id: contestId } },
          signal,
        }),
      ),
    staleTime: 10 * 60_000,
  });

export const gamePlaysQuery = (contestId: string, sourceColumns: readonly string[]) =>
  queryOptions({
    queryKey: ["games", "plays", contestId, sourceColumns.join(",")] as const,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/games/{contest_id}/plays", {
          params: {
            path: { contest_id: contestId },
            query: {
              limit: 1000,
              source_columns: sourceColumns.join(",") || null,
            },
          },
          signal,
        }),
      ),
    staleTime: 10 * 60_000,
  });

export const gameBoxQuery = (contestId: string, grain: "player" | "team") =>
  queryOptions({
    queryKey: ["games", "box", contestId, grain] as const,
    queryFn: async ({ signal }) =>
      unwrap(
        await api.GET("/api/games/{contest_id}/box", {
          params: { path: { contest_id: contestId }, query: { grain } },
          signal,
        }),
      ),
    staleTime: 10 * 60_000,
  });
