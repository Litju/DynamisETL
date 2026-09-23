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
