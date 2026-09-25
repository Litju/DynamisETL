import { queryOptions } from "@tanstack/react-query";

import type {
  EventWindowBuffers,
  PoseWindowBuffers,
  TacticalGridWindowBuffers,
  TacticalPolygonWindowBuffers,
  TrackingWindowBuffers,
} from "@/components/matchlab/frame-buffers";
import {
  prepareEventsDecodedOffThread,
  prepareEventsOffThread,
  preparePoseDecodedOffThread,
  preparePoseWindowOffThread,
  prepareTacticalGridDecodedOffThread,
  prepareTacticalGridOffThread,
  prepareTacticalPolygonsDecodedOffThread,
  prepareTacticalPolygonsOffThread,
  prepareTrackingDecodedOffThread,
  prepareTrackingWindowOffThread,
} from "@/lib/arrow/client";
import { fetchWindowArrowPrepared, type PreparedArrowWindow } from "@/lib/api/arrow-window";
import {
  queryKeys,
  type TacticalSeriesQuery,
  type WindowQuery,
} from "@/lib/api/queries";

export const trackingFrameWindowQuery = (query: WindowQuery) =>
  queryOptions({
    queryKey: queryKeys.window(query),
    queryFn: async ({ signal }) =>
      fetchWindowArrowPrepared(
        query.artifactId,
        query,
        prepareTrackingWindowOffThread,
        signal,
        prepareTrackingDecodedOffThread,
      ),
    staleTime: 30_000,
  });

export const poseFrameWindowQuery = (
  query: WindowQuery,
  jointNames: readonly string[],
) =>
  queryOptions({
    queryKey: queryKeys.window(query),
    queryFn: async ({ signal }) =>
      fetchWindowArrowPrepared(
        query.artifactId,
        query,
        (buffer) => preparePoseWindowOffThread(buffer, jointNames),
        signal,
        (decoded) => preparePoseDecodedOffThread(decoded, jointNames),
      ),
    staleTime: 30_000,
  });

export const tacticalPolygonWindowQuery = (
  query: TacticalSeriesQuery,
  objectColumn: "group_id" | "entity_id",
  polygonColumn: "hull_polygon_json" | "cell_polygon_json",
) =>
  queryOptions({
    queryKey: queryKeys.tacticalSeries(query),
    queryFn: async ({ signal }) =>
      fetchWindowArrowPrepared(
        query.artifactId,
        query,
        (buffer) => prepareTacticalPolygonsOffThread(buffer, objectColumn, polygonColumn),
        signal,
        (decoded) => prepareTacticalPolygonsDecodedOffThread(decoded, objectColumn, polygonColumn),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const tacticalGridWindowQuery = (
  query: TacticalSeriesQuery,
  valueColumn = "arrival_time_s",
  groupColumn: string | null = "owner_group_id",
) =>
  queryOptions({
    queryKey: [...queryKeys.tacticalSeries(query), "scalar-grid", valueColumn, groupColumn],
    queryFn: async ({ signal }) =>
      fetchWindowArrowPrepared(
        query.artifactId,
        query,
        (buffer) => prepareTacticalGridOffThread(buffer, valueColumn, groupColumn),
        signal,
        (decoded) => prepareTacticalGridDecodedOffThread(decoded, valueColumn, groupColumn),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const eventFrameWindowQuery = (query: WindowQuery) =>
  queryOptions({
    queryKey: queryKeys.window(query),
    queryFn: async ({ signal }) =>
      fetchWindowArrowPrepared(
        query.artifactId,
        query,
        prepareEventsOffThread,
        signal,
        prepareEventsDecodedOffThread,
      ),
    staleTime: 30_000,
  });

export type PreparedTrackingWindow = PreparedArrowWindow<TrackingWindowBuffers>;
export type PreparedPoseWindow = PreparedArrowWindow<PoseWindowBuffers>;
export type PreparedTacticalPolygonWindow = PreparedArrowWindow<TacticalPolygonWindowBuffers>;
export type PreparedTacticalGridWindow = PreparedArrowWindow<TacticalGridWindowBuffers>;
export type PreparedEventWindow = PreparedArrowWindow<EventWindowBuffers>;
