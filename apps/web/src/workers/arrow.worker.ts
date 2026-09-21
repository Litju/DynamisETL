/**
 * Arrow worker: dense decode off the main thread.
 *
 * The worker owns Arrow IPC parsing and renderer-ready typed-array shaping;
 * results cross the boundary as transferable buffers.
 */

/// <reference lib="webworker" />
import { expose, transfer } from "comlink";

import { decodeWindow, pointsForColumn, type DecodedWindow } from "@/lib/arrow/decode";

export interface ArrowWorkerApi {
  decode(buffer: ArrayBuffer): DecodedWindow;
  points(
    decoded: DecodedWindow,
    columnName: string,
    originNs: string,
  ): { xMs: Float64Array; values: Float64Array };
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
};

expose(api);
