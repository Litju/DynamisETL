import type { EntityFrame, FrameSummary, TrailPoint } from "@/components/pitch/pitch-model";
import type { TacticalOverlay } from "@/components/matchlab/render-types";

export const TRACKING_KIND = {
  player: 0,
  goalkeeper: 1,
  ball: 2,
  official: 3,
  other: 4,
} as const;

export interface TrackingWindowBuffers {
  readonly frameTimesNs: BigInt64Array;
  readonly frameOffsets: Uint32Array;
  readonly entityIds: readonly string[];
  readonly entityIndexes: Uint32Array;
  readonly teamIds: readonly string[];
  readonly teamIndexes: Int32Array;
  readonly positionsXY: Float32Array;
  readonly objectKinds: Uint8Array;
  /** 1 = detected, 0 = provider extrapolation, -1 = not declared. */
  readonly detectionState: Int8Array;
}

export interface PoseWindowBuffers {
  readonly subjectIds: readonly string[];
  readonly jointNames: readonly string[];
  /** Frames are stored in contiguous subject ranges, each ordered by canonical time. */
  readonly frameTimesNs: BigInt64Array;
  readonly subjectFrameOffsets: Uint32Array;
  readonly positionsXYZ: Float32Array;
  readonly errorM: Float32Array;
  /** A row existed for this joint; availability is distinct from row presence. */
  readonly present: Uint8Array;
  readonly availability: Uint8Array;
  readonly frameObserved: Uint8Array;
}

export interface TacticalPolygonWindowBuffers {
  readonly frameTimesNs: BigInt64Array;
  readonly framePolygonOffsets: Uint32Array;
  readonly polygonPointOffsets: Uint32Array;
  readonly positionsXY: Float32Array;
  readonly objectIds: readonly string[];
  readonly objectIndexes: Uint32Array;
  readonly groupIds: readonly string[];
  readonly groupIndexes: Int32Array;
}

export interface TacticalGridWindowBuffers {
  readonly gridTimesNs: BigInt64Array;
  readonly gridOffsets: Uint32Array;
  readonly positionsXY: Float32Array;
  readonly values: Float32Array;
  readonly groupIds: readonly string[];
  readonly groupIndexes: Int32Array;
  readonly cellWidthM: Float32Array;
  readonly cellHeightM: Float32Array;
}

export interface EventWindowBuffers {
  readonly timeNs: BigInt64Array;
  readonly positionsXY: Float32Array;
  readonly eventIds: readonly string[];
  readonly eventTypes: readonly string[];
  readonly eventSubtypes: readonly (string | null)[];
}

/** Source-frame lookup using canonical nanoseconds and an explicit age limit. */
export function trackingFrameIndexAt(
  frameTimesNs: BigInt64Array,
  targetNs: bigint | null,
  maxAgeNs: number,
): number {
  if (targetNs === null || frameTimesNs.length === 0) return -1;
  let low = 0;
  let high = frameTimesNs.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (frameTimesNs[middle]! <= targetNs) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  if (found < 0 || !Number.isFinite(maxAgeNs) || maxAgeNs < 0) return -1;
  return targetNs - frameTimesNs[found]! <= BigInt(Math.floor(maxAgeNs)) ? found : -1;
}

export function trackingFrameSummaryAt(
  buffers: TrackingWindowBuffers,
  frameIndex: number,
): FrameSummary | null {
  if (frameIndex < 0 || frameIndex >= buffers.frameTimesNs.length) return null;
  const start = buffers.frameOffsets[frameIndex]!;
  const end = buffers.frameOffsets[frameIndex + 1]!;
  let players = 0;
  let extrapolated = 0;
  let ballDetected: boolean | null = null;
  for (let row = start; row < end; row += 1) {
    const kind = buffers.objectKinds[row] ?? TRACKING_KIND.other;
    const state = buffers.detectionState[row] ?? -1;
    if (kind === TRACKING_KIND.ball) {
      ballDetected = state < 0 ? null : state === 1;
    } else {
      players += 1;
    }
    if (state === 0) extrapolated += 1;
  }
  return {
    tRelNs: Number(buffers.frameTimesNs[frameIndex]!),
    players,
    extrapolated,
    ballDetected,
  };
}

export function trackingEntityAt(
  buffers: TrackingWindowBuffers,
  frameIndex: number,
  objectId: string | null,
): EntityFrame | null {
  if (objectId === null || frameIndex < 0 || frameIndex >= buffers.frameTimesNs.length) return null;
  const entityIndex = buffers.entityIds.indexOf(objectId);
  if (entityIndex < 0) return null;
  const start = buffers.frameOffsets[frameIndex]!;
  const end = buffers.frameOffsets[frameIndex + 1]!;
  for (let row = start; row < end; row += 1) {
    if (buffers.entityIndexes[row] !== entityIndex) continue;
    const kind = buffers.objectKinds[row] ?? TRACKING_KIND.other;
    const groupIndex = buffers.teamIndexes[row] ?? -1;
    const detected = buffers.detectionState[row] ?? -1;
    return {
      objectId,
      objectType:
        kind === TRACKING_KIND.player
          ? "player"
          : kind === TRACKING_KIND.goalkeeper
            ? "goalkeeper"
            : kind === TRACKING_KIND.ball
              ? "ball"
              : kind === TRACKING_KIND.official
                ? "official"
                : "other",
      groupId: groupIndex < 0 ? null : (buffers.teamIds[groupIndex] ?? null),
      xM: buffers.positionsXY[row * 2] ?? Number.NaN,
      yM: buffers.positionsXY[row * 2 + 1] ?? Number.NaN,
      detected: detected < 0 ? null : detected === 1,
      isBall: kind === TRACKING_KIND.ball,
    };
  }
  return null;
}

export function trailPointsForTrackingBuffer(
  buffers: TrackingWindowBuffers,
  range: { readonly fromNs: bigint; readonly toNs: bigint } | null,
  objectId: string | null,
): TrailPoint[] {
  if (objectId === null) return [];
  const entityIndex = buffers.entityIds.indexOf(objectId);
  if (entityIndex < 0) return [];
  const points: TrailPoint[] = [];
  for (let frame = 0; frame < buffers.frameTimesNs.length; frame += 1) {
    const timeNs = buffers.frameTimesNs[frame]!;
    if (range !== null && (timeNs < range.fromNs || timeNs > range.toNs)) continue;
    for (let row = buffers.frameOffsets[frame]!; row < buffers.frameOffsets[frame + 1]!; row += 1) {
      if (buffers.entityIndexes[row] !== entityIndex) continue;
      const detected = buffers.detectionState[row] ?? -1;
      points.push({
        objectId,
        xM: buffers.positionsXY[row * 2] ?? Number.NaN,
        yM: buffers.positionsXY[row * 2 + 1] ?? Number.NaN,
        detected: detected < 0 ? null : detected === 1,
      });
      break;
    }
  }
  return points;
}

export function tacticalOverlayAtBuffers(
  buffers: {
    readonly geometry: TacticalPolygonWindowBuffers;
    readonly territory: TacticalPolygonWindowBuffers;
    readonly influence: TacticalGridWindowBuffers;
  },
  frameTimeNs: bigint | null,
  roleOf: (groupId: string) => "home" | "away" | "other",
  influenceMaxAgeNs: number,
): { readonly overlay: TacticalOverlay; readonly influenceGridTimeNs: bigint | null } {
  const exactIndex = (times: BigInt64Array, timeNs: bigint | null): number => {
    if (timeNs === null) return -1;
    let low = 0;
    let high = times.length - 1;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      if (times[middle] === timeNs) return middle;
      if (times[middle]! < timeNs) low = middle + 1;
      else high = middle - 1;
    }
    return -1;
  };
  const polygonsAt = (
    buffers: TacticalPolygonWindowBuffers,
    frameIndex: number,
    isTerritory: boolean,
  ) => {
    const polygons: Array<{
      readonly groupId: string;
      readonly role: "home" | "away" | "other";
      readonly entityId?: string;
      readonly points: readonly [number, number][];
    }> = [];
    for (let polygon = buffers.framePolygonOffsets[frameIndex]!;
      polygon < buffers.framePolygonOffsets[frameIndex + 1]!;
      polygon += 1) {
      const objectId = buffers.objectIds[buffers.objectIndexes[polygon]!];
      const groupId = buffers.groupIds[buffers.groupIndexes[polygon]!];
      if (objectId === undefined || groupId === undefined) continue;
      const start = buffers.polygonPointOffsets[polygon]!;
      const end = buffers.polygonPointOffsets[polygon + 1]!;
      const points = Array.from({ length: end - start }, (_, offset) => [
        buffers.positionsXY[(start + offset) * 2]!,
        buffers.positionsXY[(start + offset) * 2 + 1]!,
      ] as [number, number]);
      if (points.length < (isTerritory ? 3 : 2)) continue;
      polygons.push({
        ...(isTerritory ? { entityId: objectId } : {}),
        groupId,
        role: roleOf(groupId),
        points,
      });
    }
    return polygons;
  };

  const geometryIndex = exactIndex(buffers.geometry.frameTimesNs, frameTimeNs);
  const territoryIndex = exactIndex(buffers.territory.frameTimesNs, frameTimeNs);
  let gridIndex = -1;
  if (frameTimeNs !== null) {
    let low = 0;
    let high = buffers.influence.gridTimesNs.length - 1;
    while (low <= high) {
      const middle = Math.floor((low + high) / 2);
      if (buffers.influence.gridTimesNs[middle]! <= frameTimeNs) {
        gridIndex = middle;
        low = middle + 1;
      } else high = middle - 1;
    }
    if (gridIndex >= 0 && frameTimeNs - buffers.influence.gridTimesNs[gridIndex]! > BigInt(Math.floor(influenceMaxAgeNs))) {
      gridIndex = -1;
    }
  }
  const influenceCells: TacticalOverlay["influenceCells"][number][] = [];
  if (gridIndex >= 0) {
    for (let cell = buffers.influence.gridOffsets[gridIndex]!; cell < buffers.influence.gridOffsets[gridIndex + 1]!; cell += 1) {
      const groupId = buffers.influence.groupIds[buffers.influence.groupIndexes[cell]!];
      if (groupId === undefined) continue;
      influenceCells.push({
        xM: buffers.influence.positionsXY[cell * 2]!,
        yM: buffers.influence.positionsXY[cell * 2 + 1]!,
        widthM: buffers.influence.cellWidthM[gridIndex]!,
        heightM: buffers.influence.cellHeightM[gridIndex]!,
        groupId,
        role: roleOf(groupId),
        arrivalTimeS: buffers.influence.values[cell]!,
      });
    }
  }
  return {
    overlay: {
      hulls: geometryIndex < 0 ? [] : polygonsAt(buffers.geometry, geometryIndex, false),
      territoryCells: territoryIndex < 0 ? [] : polygonsAt(buffers.territory, territoryIndex, true) as TacticalOverlay["territoryCells"],
      influenceCells,
    },
    influenceGridTimeNs: influenceCells.length > 0 && gridIndex >= 0 ? buffers.influence.gridTimesNs[gridIndex]! : null,
  };
}

export function poseBufferFrameIndexAt(
  buffers: PoseWindowBuffers,
  subjectId: string,
  targetNs: bigint | null,
  maxAgeNs: number,
): number {
  const subjectIndex = buffers.subjectIds.indexOf(subjectId);
  if (subjectIndex < 0) return -1;
  const start = buffers.subjectFrameOffsets[subjectIndex] ?? 0;
  const end = buffers.subjectFrameOffsets[subjectIndex + 1] ?? start;
  if (targetNs === null) {
    for (let frame = start; frame < end; frame += 1) {
      if (buffers.frameObserved[frame] === 1) return frame;
    }
    return -1;
  }
  let low = start;
  let high = end - 1;
  let found = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (buffers.frameTimesNs[middle]! <= targetNs) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  if (!Number.isFinite(maxAgeNs) || maxAgeNs < 0) return -1;
  const allowedAge = BigInt(Math.floor(maxAgeNs));
  for (let frame = found; frame >= start; frame -= 1) {
    if (targetNs - buffers.frameTimesNs[frame]! > allowedAge) break;
    if (buffers.frameObserved[frame] === 1) return frame;
  }
  return -1;
}
