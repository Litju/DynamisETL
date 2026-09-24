/**
 * Arrow worker: dense decode off the main thread.
 *
 * The worker owns Arrow IPC parsing and renderer-ready typed-array shaping;
 * results cross the boundary as transferable buffers.
 */

/// <reference lib="webworker" />
import { expose, transfer } from "comlink";

import type {
  EventWindowBuffers,
  PoseWindowBuffers,
  TacticalGridWindowBuffers,
  TacticalPolygonWindowBuffers,
  TrackingWindowBuffers,
} from "@/components/matchlab/frame-buffers";
import { decodeWindow, pointsForColumn, type DecodedWindow } from "@/lib/arrow/decode";
import {
  prepareEventWindow,
  preparePoseWindow,
  prepareTacticalGridWindow,
  prepareTacticalPolygonWindow,
  prepareTrackingWindow,
} from "@/lib/arrow/match-frame-preparation";

export interface ArrowWorkerApi {
  decode(buffer: ArrayBuffer): DecodedWindow;
  points(
    decoded: DecodedWindow,
    columnName: string,
    originNs: string,
  ): { xMs: Float64Array; values: Float64Array };
  prepareTracking(buffer: ArrayBuffer | DecodedWindow): TrackingWindowBuffers;
  preparePose(buffer: ArrayBuffer | DecodedWindow, jointNames: readonly string[]): PoseWindowBuffers;
  prepareTacticalPolygons(
    buffer: ArrayBuffer | DecodedWindow,
    objectColumn: "group_id" | "entity_id",
    polygonColumn: "hull_polygon_json" | "cell_polygon_json",
  ): TacticalPolygonWindowBuffers;
  prepareTacticalGrid(buffer: ArrayBuffer | DecodedWindow): TacticalGridWindowBuffers;
  prepareEvents(buffer: ArrayBuffer | DecodedWindow): EventWindowBuffers;
}

function decodedInput(input: ArrayBuffer | DecodedWindow): DecodedWindow {
  return input instanceof ArrayBuffer ? decodeWindow(input) : input;
}

function transferTracking(data: TrackingWindowBuffers): TrackingWindowBuffers {
  return transfer(data, [
    data.frameTimesNs.buffer as ArrayBuffer,
    data.frameOffsets.buffer as ArrayBuffer,
    data.entityIndexes.buffer as ArrayBuffer,
    data.teamIndexes.buffer as ArrayBuffer,
    data.positionsXY.buffer as ArrayBuffer,
    data.objectKinds.buffer as ArrayBuffer,
    data.detectionState.buffer as ArrayBuffer,
  ]);
}

function transferPose(data: PoseWindowBuffers): PoseWindowBuffers {
  return transfer(data, [
    data.frameTimesNs.buffer as ArrayBuffer,
    data.subjectFrameOffsets.buffer as ArrayBuffer,
    data.positionsXYZ.buffer as ArrayBuffer,
    data.errorM.buffer as ArrayBuffer,
    data.present.buffer as ArrayBuffer,
    data.availability.buffer as ArrayBuffer,
    data.frameObserved.buffer as ArrayBuffer,
  ]);
}

function transferPolygons(data: TacticalPolygonWindowBuffers): TacticalPolygonWindowBuffers {
  return transfer(data, [
    data.frameTimesNs.buffer as ArrayBuffer,
    data.framePolygonOffsets.buffer as ArrayBuffer,
    data.polygonPointOffsets.buffer as ArrayBuffer,
    data.positionsXY.buffer as ArrayBuffer,
    data.objectIndexes.buffer as ArrayBuffer,
    data.groupIndexes.buffer as ArrayBuffer,
  ]);
}

function transferGrid(data: TacticalGridWindowBuffers): TacticalGridWindowBuffers {
  return transfer(data, [
    data.gridTimesNs.buffer as ArrayBuffer,
    data.gridOffsets.buffer as ArrayBuffer,
    data.positionsXY.buffer as ArrayBuffer,
    data.values.buffer as ArrayBuffer,
    data.groupIndexes.buffer as ArrayBuffer,
    data.cellWidthM.buffer as ArrayBuffer,
    data.cellHeightM.buffer as ArrayBuffer,
  ]);
}

function transferEvents(data: EventWindowBuffers): EventWindowBuffers {
  return transfer(data, [
    data.timeNs.buffer as ArrayBuffer,
    data.positionsXY.buffer as ArrayBuffer,
  ]);
}

const api: ArrowWorkerApi = {
  decode(buffer) {
    const decoded = decodeWindow(buffer);
    const transfers = [
      decoded.timeNs.buffer as ArrayBuffer,
      ...decoded.columns.flatMap((column) =>
        column.values instanceof Float64Array
          ? [column.values.buffer as ArrayBuffer]
          : [],
      ),
    ];
    return transfer(decoded, transfers);
  },
  points(decoded, columnName, originNs) {
    const interleaved = pointsForColumn(decoded, columnName, BigInt(originNs));
    const count = interleaved.length / 2;
    const xMs = new Float64Array(count);
    const values = new Float64Array(count);
    for (let index = 0; index < count; index += 1) {
      xMs[index] = interleaved[index * 2] ?? Number.NaN;
      values[index] = interleaved[index * 2 + 1] ?? Number.NaN;
    }
    return transfer({ xMs, values }, [xMs.buffer, values.buffer]);
  },
  prepareTracking(buffer) {
    return transferTracking(prepareTrackingWindow(decodedInput(buffer)));
  },
  preparePose(buffer, jointNames) {
    return transferPose(preparePoseWindow(decodedInput(buffer), jointNames));
  },
  prepareTacticalPolygons(buffer, objectColumn, polygonColumn) {
    return transferPolygons(
      prepareTacticalPolygonWindow(decodedInput(buffer), objectColumn, polygonColumn),
    );
  },
  prepareTacticalGrid(buffer) {
    return transferGrid(prepareTacticalGridWindow(decodedInput(buffer)));
  },
  prepareEvents(buffer) {
    return transferEvents(prepareEventWindow(decodedInput(buffer)));
  },
};

expose(api);
