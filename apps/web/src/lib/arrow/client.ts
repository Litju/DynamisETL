/**
 * Comlink client for the Arrow worker.
 *
 * The worker is created lazily so routes that never touch dense transport do
 * not download the Arrow decoder, and a missing Worker implementation (tests,
 * SSR) degrades to synchronous decode instead of failing the surface.
 */

import { transfer, wrap, type Remote } from "comlink";

import type {
  EventWindowBuffers,
  PoseWindowBuffers,
  TacticalGridWindowBuffers,
  TacticalPolygonWindowBuffers,
  TrackingWindowBuffers,
} from "@/components/matchlab/frame-buffers";
import type { DecodedWindow } from "@/lib/arrow/decode";
import type { ArrowWorkerApi } from "@/workers/arrow.worker";

let remote: Remote<ArrowWorkerApi> | null = null;
let unavailable = false;

/**
 * Unit tests and SSR decode synchronously: jsdom has no module worker runtime,
 * and the Arrow IPC contract itself is covered by the pure decode kernels that
 * the worker also calls.
 */
function prefersSynchronousDecode(): boolean {
  return import.meta.env.MODE === "test" || Boolean(import.meta.env.SSR);
}

function getWorker(): Remote<ArrowWorkerApi> | null {
  if (unavailable || prefersSynchronousDecode()) return null;
  if (remote) return remote;
  if (typeof Worker === "undefined") {
    unavailable = true;
    return null;
  }
  try {
    const worker = new Worker(new URL("../../workers/arrow.worker.ts", import.meta.url), {
      type: "module",
      name: "dynamis-arrow",
    });
    remote = wrap<ArrowWorkerApi>(worker);
    return remote;
  } catch {
    unavailable = true;
    return null;
  }
}

export async function decodeWindowOffThread(
  buffer: ArrayBuffer,
): Promise<DecodedWindow> {
  const worker = getWorker();
  if (!worker) {
    // Lazy so the Arrow decoder is not in the shell/catalog chunk.
    const { decodeWindow } = await import("@/lib/arrow/decode");
    return decodeWindow(buffer);
  }
  return worker.decode(transfer(buffer, [buffer]));
}

function transferDecodedWindow(decoded: DecodedWindow): DecodedWindow {
  return transfer(decoded, [
    decoded.timeNs.buffer as ArrayBuffer,
    ...decoded.columns.flatMap((column) =>
      column.values instanceof Float64Array ? [column.values.buffer as ArrayBuffer] : [],
    ),
  ]);
}

export async function prepareTrackingWindowOffThread(buffer: ArrayBuffer): Promise<TrackingWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.prepareTracking(transfer(buffer, [buffer]));
  const [{ decodeWindow }, { prepareTrackingWindow }] = await Promise.all([
    import("@/lib/arrow/decode"),
    import("@/lib/arrow/match-frame-preparation"),
  ]);
  return prepareTrackingWindow(decodeWindow(buffer));
}

export async function prepareTrackingDecodedOffThread(decoded: DecodedWindow): Promise<TrackingWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.prepareTracking(transferDecodedWindow(decoded));
  const { prepareTrackingWindow } = await import("@/lib/arrow/match-frame-preparation");
  return prepareTrackingWindow(decoded);
}

export async function preparePoseWindowOffThread(
  buffer: ArrayBuffer,
  jointNames: readonly string[],
): Promise<PoseWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.preparePose(transfer(buffer, [buffer]), jointNames);
  const [{ decodeWindow }, { preparePoseWindow }] = await Promise.all([
    import("@/lib/arrow/decode"),
    import("@/lib/arrow/match-frame-preparation"),
  ]);
  return preparePoseWindow(decodeWindow(buffer), jointNames);
}

export async function preparePoseDecodedOffThread(
  decoded: DecodedWindow,
  jointNames: readonly string[],
): Promise<PoseWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.preparePose(transferDecodedWindow(decoded), jointNames);
  const { preparePoseWindow } = await import("@/lib/arrow/match-frame-preparation");
  return preparePoseWindow(decoded, jointNames);
}

export async function prepareTacticalPolygonsOffThread(
  buffer: ArrayBuffer,
  objectColumn: "group_id" | "entity_id",
  polygonColumn: "hull_polygon_json" | "cell_polygon_json",
): Promise<TacticalPolygonWindowBuffers> {
  const worker = getWorker();
  if (worker) {
    return worker.prepareTacticalPolygons(
      transfer(buffer, [buffer]),
      objectColumn,
      polygonColumn,
    );
  }
  const [{ decodeWindow }, { prepareTacticalPolygonWindow }] = await Promise.all([
    import("@/lib/arrow/decode"),
    import("@/lib/arrow/match-frame-preparation"),
  ]);
  return prepareTacticalPolygonWindow(
    decodeWindow(buffer),
    objectColumn,
    polygonColumn,
  );
}

export async function prepareTacticalPolygonsDecodedOffThread(
  decoded: DecodedWindow,
  objectColumn: "group_id" | "entity_id",
  polygonColumn: "hull_polygon_json" | "cell_polygon_json",
): Promise<TacticalPolygonWindowBuffers> {
  const worker = getWorker();
  if (worker) {
    return worker.prepareTacticalPolygons(
      transferDecodedWindow(decoded),
      objectColumn,
      polygonColumn,
    );
  }
  const { prepareTacticalPolygonWindow } = await import("@/lib/arrow/match-frame-preparation");
  return prepareTacticalPolygonWindow(decoded, objectColumn, polygonColumn);
}

export async function prepareTacticalGridOffThread(
  buffer: ArrayBuffer,
  valueColumn = "arrival_time_s",
  groupColumn: string | null = "owner_group_id",
): Promise<TacticalGridWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.prepareTacticalGrid(transfer(buffer, [buffer]), valueColumn, groupColumn);
  const [{ decodeWindow }, { prepareTacticalGridWindow }] = await Promise.all([
    import("@/lib/arrow/decode"),
    import("@/lib/arrow/match-frame-preparation"),
  ]);
  return prepareTacticalGridWindow(decodeWindow(buffer), valueColumn, groupColumn);
}

export async function prepareTacticalGridDecodedOffThread(
  decoded: DecodedWindow,
  valueColumn = "arrival_time_s",
  groupColumn: string | null = "owner_group_id",
): Promise<TacticalGridWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.prepareTacticalGrid(transferDecodedWindow(decoded), valueColumn, groupColumn);
  const { prepareTacticalGridWindow } = await import("@/lib/arrow/match-frame-preparation");
  return prepareTacticalGridWindow(decoded, valueColumn, groupColumn);
}

export async function prepareEventsOffThread(buffer: ArrayBuffer): Promise<EventWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.prepareEvents(transfer(buffer, [buffer]));
  const [{ decodeWindow }, { prepareEventWindow }] = await Promise.all([
    import("@/lib/arrow/decode"),
    import("@/lib/arrow/match-frame-preparation"),
  ]);
  return prepareEventWindow(decodeWindow(buffer));
}

export async function prepareEventsDecodedOffThread(decoded: DecodedWindow): Promise<EventWindowBuffers> {
  const worker = getWorker();
  if (worker) return worker.prepareEvents(transferDecodedWindow(decoded));
  const { prepareEventWindow } = await import("@/lib/arrow/match-frame-preparation");
  return prepareEventWindow(decoded);
}

export function resetArrowClientForTests(): void {
  remote = null;
  unavailable = false;
}
