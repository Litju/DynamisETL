import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";

import type { DenseWindow } from "@/api/types";
import { windowQuery, type WindowQuery } from "@/lib/api/queries";
import type { DenseChunkBounds, DenseChunkPlan } from "@/lib/dense-chunks";
import {
  usePlaybackChunkCoordinator,
  type PlaybackChunkQueryOptions,
} from "@/lib/playback-chunk-coordinator";

export const POSE_COLUMNS = [
  "t_rel_ns",
  "subject_id",
  "joint_name",
  "is_available",
  "x_m",
  "y_m",
  "z_m",
  "error_m",
] as const;

export interface PosePlaybackWindowOptions {
  readonly artifactId: string | null;
  readonly entityId: string | null;
  readonly canonicalMinNs: bigint | null;
  readonly canonicalMaxNs: bigint | null;
  readonly chunkSpanNs: bigint | null;
  readonly anchorNs: bigint | null;
  readonly explicitFromNs?: bigint | null;
  readonly explicitToNs?: bigint | null;
  readonly maxPoints: number;
}

export interface PosePlaybackWindowResult {
  readonly window: ReturnType<typeof useQuery<DenseWindow>>;
  readonly chunkPlan: DenseChunkPlan | null;
  readonly activeWindowBounds: DenseChunkBounds | { readonly fromNs: bigint; readonly toNs: bigint } | null;
  readonly playbackStatus: "idle" | "ready" | "buffering" | "ended";
}

/** Pose and the inspector telemetry share one exact-window query authority. */
export function usePosePlaybackWindow(options: PosePlaybackWindowOptions): PosePlaybackWindowResult {
  const queryClient = useQueryClient();
  const request = useMemo<WindowQuery>(
    () => ({
      artifactId: options.artifactId ?? "",
      ...(options.entityId !== null ? { entityId: options.entityId } : {}),
      columns: POSE_COLUMNS,
      maxPoints: options.maxPoints,
    }),
    [options.artifactId, options.entityId, options.maxPoints],
  );
  const queryOptionsFor = useCallback(
    (chunk: DenseChunkBounds): PlaybackChunkQueryOptions<DenseWindow> =>
      windowQuery({
        ...request,
        fromNs: Number(chunk.fromNs),
        toNs: Number(chunk.toNs),
        cacheScope: "dense-chunk",
        chunkId: chunk.id,
      }) as unknown as PlaybackChunkQueryOptions<DenseWindow>,
    [request],
  );
  const queryScope = useMemo(
    () => ({
      artifactId: request.artifactId,
      columns: request.columns?.join(",") ?? null,
      maxPoints: request.maxPoints ?? null,
      entityId: request.entityId ?? null,
    }),
    [request],
  );
  const explicit =
    options.explicitFromNs !== null && options.explicitFromNs !== undefined &&
    options.explicitToNs !== null && options.explicitToNs !== undefined
      ? { fromNs: options.explicitFromNs, toNs: options.explicitToNs }
      : null;
  const playback = usePlaybackChunkCoordinator<DenseWindow>({
    enabled: explicit === null,
    canonicalMinNs: options.canonicalMinNs,
    canonicalMaxNs: options.canonicalMaxNs,
    chunkSpanNs: options.chunkSpanNs,
    anchorNs: options.anchorNs,
    queryClient,
    queryOptionsFor,
    isReady: (data) => data?.meta.reduction === null,
    matchesQuery: (key) =>
      key[0] === "dense-chunk" &&
      key[1] === queryScope.artifactId &&
      key[6] === queryScope.columns &&
      key[7] === queryScope.maxPoints &&
      key[8] === queryScope.entityId,
    chunkIdFromQueryKey: (key) => (typeof key[3] === "string" ? key[3] : null),
  });
  const activeChunk = playback.plan?.active ?? null;
  const activeQuery = useMemo(() => {
    if (activeChunk !== null) {
      return windowQuery({
        ...request,
        fromNs: Number(activeChunk.fromNs),
        toNs: Number(activeChunk.toNs),
        cacheScope: "dense-chunk",
        chunkId: activeChunk.id,
      });
    }
    return windowQuery({
      ...request,
      ...(explicit !== null ? { fromNs: Number(explicit.fromNs), toNs: Number(explicit.toNs) } : {}),
    });
  }, [activeChunk, explicit, request]);
  const window = useQuery({
    ...activeQuery,
    enabled: Boolean(options.artifactId) && (explicit !== null || activeChunk !== null),
  });
  return {
    window,
    chunkPlan: playback.plan,
    activeWindowBounds: activeChunk ?? explicit,
    playbackStatus: playback.status,
  };
}
