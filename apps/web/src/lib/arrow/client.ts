/**
 * Comlink client for the Arrow worker.
 *
 * The worker is created lazily so routes that never touch dense transport do
 * not download the Arrow decoder, and a missing Worker implementation (tests,
 * SSR) degrades to synchronous decode instead of failing the surface.
 */

import { wrap, type Remote } from "comlink";

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
  return worker.decode(buffer);
}

export function resetArrowClientForTests(): void {
  remote = null;
  unavailable = false;
}
