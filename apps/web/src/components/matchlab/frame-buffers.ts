import type { TrackingFrame } from "@/components/pitch/pitch-model";

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

/** ponytail: temporary main-thread adapter; gate 6 moves this conversion into the Arrow worker. */
export function trackingBuffersFromFrames(frames: readonly TrackingFrame[]): TrackingWindowBuffers {
  const entityIds = [...new Set(frames.flatMap((frame) => frame.entities.map((entity) => entity.objectId)))].sort();
  const teamIds = [...new Set(
    frames.flatMap((frame) =>
      frame.entities.flatMap((entity) => (entity.groupId === null ? [] : [entity.groupId])),
    ),
  )].sort();
  const entityIndex = new Map(entityIds.map((id, index) => [id, index]));
  const teamIndex = new Map(teamIds.map((id, index) => [id, index]));
  const rowCount = frames.reduce((count, frame) => count + frame.entities.length, 0);
  const frameTimesNs = new BigInt64Array(frames.length);
  const frameOffsets = new Uint32Array(frames.length + 1);
  const entityIndexes = new Uint32Array(rowCount);
  const teamIndexes = new Int32Array(rowCount);
  const positionsXY = new Float32Array(rowCount * 2);
  const objectKinds = new Uint8Array(rowCount);
  const detectionState = new Int8Array(rowCount);
  let rowIndex = 0;

  for (let frameIndex = 0; frameIndex < frames.length; frameIndex += 1) {
    const frame = frames[frameIndex]!;
    frameTimesNs[frameIndex] = BigInt(Math.trunc(frame.tRelNs));
    frameOffsets[frameIndex] = rowIndex;
    for (const entity of frame.entities) {
      entityIndexes[rowIndex] = entityIndex.get(entity.objectId)!;
      teamIndexes[rowIndex] = entity.groupId === null ? -1 : teamIndex.get(entity.groupId)!;
      positionsXY[rowIndex * 2] = entity.xM;
      positionsXY[rowIndex * 2 + 1] = entity.yM;
      objectKinds[rowIndex] =
        entity.objectType === "player"
          ? TRACKING_KIND.player
          : entity.objectType === "goalkeeper"
            ? TRACKING_KIND.goalkeeper
            : entity.objectType === "ball"
              ? TRACKING_KIND.ball
              : entity.objectType === "official"
                ? TRACKING_KIND.official
                : TRACKING_KIND.other;
      detectionState[rowIndex] = entity.detected === null ? -1 : entity.detected ? 1 : 0;
      rowIndex += 1;
    }
  }
  frameOffsets[frames.length] = rowIndex;
  return {
    frameTimesNs,
    frameOffsets,
    entityIds,
    entityIndexes,
    teamIds,
    teamIndexes,
    positionsXY,
    objectKinds,
    detectionState,
  };
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
