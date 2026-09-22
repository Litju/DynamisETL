import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import type { DenseWindowMeta } from "@/api/types";
import { api, unwrap } from "@/lib/api/client";
import {
  ArrowTransportUnsupportedError,
  fetchWindowArrow,
} from "@/lib/api/arrow-window";
import { tableFromDecoded, tableFromJson, type WindowTable } from "@/lib/arrow/window-table";
import { type DenseChunkConfig, type DenseChunkBounds } from "@/lib/dense-chunks";
import {
  usePlaybackChunkCoordinator,
  type PlaybackChunkQueryOptions,
} from "@/lib/playback-chunk-coordinator";

export interface DenseWindowRequest {
  readonly artifactId: string | null;
  readonly fromNs?: number | undefined;
  readonly toNs?: number | undefined;
  readonly columns?: readonly string[] | undefined;
  readonly maxPoints?: number | undefined;
  readonly entityId?: string | undefined;
  readonly chunk?: DenseChunkConfig | undefined;
  readonly cacheScope?: "dense-window" | "dense-chunk-window" | undefined;
  readonly chunkId?: string | undefined;
}

export interface DenseWindowState {
  readonly table: WindowTable | null;
  readonly transport: "arrow" | "json" | null;
  readonly meta: DenseWindowMeta | null;
}

function queryKey(request: DenseWindowRequest): QueryKey {
  return [
    request.cacheScope ?? "dense-window",
    request.artifactId,
    "window",
    request.chunkId ?? "single",
    request.fromNs ?? null,
    request.toNs ?? null,
    request.columns?.join(",") ?? null,
    request.maxPoints ?? null,
    request.entityId ?? null,
  ];
}

export async function fetchDenseWindow(
  request: DenseWindowRequest,
  signal?: AbortSignal,
): Promise<DenseWindowState> {
  const artifactId = request.artifactId ?? "";
  try {
    const arrow = await fetchWindowArrow(artifactId, {
      ...(request.fromNs !== undefined ? { fromNs: request.fromNs } : {}),
      ...(request.toNs !== undefined ? { toNs: request.toNs } : {}),
      ...(request.columns !== undefined ? { columns: request.columns } : {}),
      ...(request.maxPoints !== undefined ? { maxPoints: request.maxPoints } : {}),
      ...(request.entityId !== undefined ? { entityId: request.entityId } : {}),
    }, signal);
    return { table: tableFromDecoded(arrow.decoded, arrow.meta), transport: "arrow", meta: arrow.meta };
  } catch (error) {
    if (!(error instanceof ArrowTransportUnsupportedError)) throw error;
    const json = await unwrap(await api.GET("/api/artifacts/{artifact_id}/window", {
      params: {
        path: { artifact_id: artifactId },
        query: {
          ...(request.fromNs !== undefined ? { from_ns: request.fromNs } : {}),
          ...(request.toNs !== undefined ? { to_ns: request.toNs } : {}),
          ...(request.columns !== undefined ? { columns: request.columns.join(",") } : {}),
          ...(request.maxPoints !== undefined ? { max_points: request.maxPoints } : {}),
          ...(request.entityId !== undefined ? { entity_id: request.entityId } : {}),
        },
      },
      ...(signal ? { signal } : {}),
    }));
    return { table: tableFromJson(json), transport: "json", meta: json.meta };
  }
}

export function denseWindowQueryOptions(request: DenseWindowRequest) {
  return {
    queryKey: queryKey(request),
    queryFn: ({ signal }: { signal: AbortSignal }) => fetchDenseWindow(request, signal),
    staleTime: 30_000,
    gcTime: request.cacheScope === "dense-chunk-window" ? 30_000 : 5 * 60_000,
  };
}

/** Dense transport with the shared playhead-driven chunk coordinator. */
export function useDenseWindow(request: DenseWindowRequest) {
  const queryClient = useQueryClient();
  const queryOptionsFor = useCallback(
    (chunk: DenseChunkBounds): PlaybackChunkQueryOptions<DenseWindowState> =>
      denseWindowQueryOptions({
        ...request,
        fromNs: Number(chunk.fromNs),
        toNs: Number(chunk.toNs),
        cacheScope: "dense-chunk-window",
        chunkId: chunk.id,
      }),
    [request],
  );
  const queryScope = useMemo(
    () => ({
      artifactId: request.artifactId,
      columns: request.columns?.join(",") ?? null,
      maxPoints: request.maxPoints ?? null,
      entityId: request.entityId ?? null,
    }),
    [request.artifactId, request.columns, request.entityId, request.maxPoints],
  );
  const playback = usePlaybackChunkCoordinator<DenseWindowState>({
    enabled: request.chunk !== undefined,
    canonicalMinNs: request.chunk?.canonicalMinNs ?? null,
    canonicalMaxNs: request.chunk?.canonicalMaxNs ?? null,
    chunkSpanNs: request.chunk?.chunkSpanNs ?? null,
    anchorNs: request.chunk?.anchorNs ?? null,
    queryClient,
    queryOptionsFor,
    isReady: (data) => data?.table !== null && data?.table !== undefined,
    matchesQuery: (key) =>
      key[0] === "dense-chunk-window" &&
      key[1] === queryScope.artifactId &&
      key[6] === queryScope.columns &&
      key[7] === queryScope.maxPoints &&
      key[8] === queryScope.entityId,
    chunkIdFromQueryKey: (key) => (typeof key[3] === "string" ? key[3] : null),
  });
  const plan = playback.plan;
  const activeRequest = useMemo<DenseWindowRequest>(() => {
    if (!plan) return request;
    return {
      ...request,
      fromNs: Number(plan.active.fromNs),
      toNs: Number(plan.active.toNs),
      cacheScope: "dense-chunk-window",
      chunkId: plan.active.id,
    };
  }, [plan, request]);
  const query = useQuery({
    ...denseWindowQueryOptions(activeRequest),
    enabled: Boolean(activeRequest.artifactId) && (request.chunk === undefined || plan !== null),
  });

  return { ...query, chunkPlan: plan, playbackStatus: playback.status };
}
