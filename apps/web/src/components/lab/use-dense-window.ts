import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import type { DenseWindowMeta } from "@/api/types";
import { api, unwrap } from "@/lib/api/client";
import {
  ArrowTransportUnsupportedError,
  fetchWindowArrow,
} from "@/lib/api/arrow-window";
import { tableFromDecoded, tableFromJson, type WindowTable } from "@/lib/arrow/window-table";
import { windowQuery, type WindowQuery } from "@/lib/api/queries";
import { planDenseChunks, type DenseChunkConfig, type DenseChunkPlan } from "@/lib/dense-chunks";

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

/**
 * Dense transport with a bounded active/previous/next cache. Chunk identity is
 * canonical and non-overlapping; React Query aborts stale Arrow requests when
 * the analytical context changes.
 */
export function useDenseWindow(request: DenseWindowRequest) {
  const queryClient = useQueryClient();
  const plan = useMemo<DenseChunkPlan | null>(
    () => (request.chunk ? planDenseChunks(request.chunk) : null),
    [request.chunk],
  );
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
    enabled: Boolean(activeRequest.artifactId),
  });

  useEffect(() => {
    if (!plan) return;
    const adjacent = [plan.previous, plan.next].filter((chunk): chunk is NonNullable<typeof chunk> => chunk !== null);
    const allowed = new Set([plan.active.id, ...adjacent.map((chunk) => chunk.id)]);
    queryClient.removeQueries({
      queryKey: ["dense-chunk-window"],
      predicate: (candidate) => !allowed.has(String(candidate.queryKey[3] ?? "")),
    });
    void Promise.all(adjacent.map((chunk) => queryClient.prefetchQuery(denseWindowQueryOptions({
      ...request,
      fromNs: Number(chunk.fromNs),
      toNs: Number(chunk.toNs),
      cacheScope: "dense-chunk-window",
      chunkId: chunk.id,
    }))));
  }, [plan, queryClient, request]);

  return { ...query, chunkPlan: plan };
}

export function useDenseChunkPrefetch(
  request: Omit<WindowQuery, "fromNs" | "toNs" | "cacheScope" | "chunkId">,
  plan: DenseChunkPlan | null,
) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!plan) return;
    const adjacent = [plan.previous, plan.next].filter((chunk): chunk is NonNullable<typeof chunk> => chunk !== null);
    const allowed = new Set([plan.active.id, ...adjacent.map((chunk) => chunk.id)]);
    queryClient.removeQueries({
      queryKey: ["dense-chunk"],
      predicate: (candidate) => !allowed.has(String(candidate.queryKey[3] ?? "")),
    });
    void Promise.all(adjacent.map((chunk) => queryClient.prefetchQuery(windowQuery({
      ...request,
      fromNs: Number(chunk.fromNs),
      toNs: Number(chunk.toNs),
      cacheScope: "dense-chunk",
      chunkId: chunk.id,
    }))));
  }, [plan, queryClient, request]);
}
