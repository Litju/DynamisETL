/**
 * Canonical time model.
 *
 * `t_rel_ns` is the scientific time authority and stays an exact integer. URL
 * state carries it as decimal nanosecond text; renderers convert to a bounded
 * millisecond offset from a viewport origin, and convert selections back to
 * exact nanoseconds. Absolute nanosecond values never enter floating-point
 * chart coordinates.
 */

export const NS_PER_MICROSECOND = 1_000n;
export const NS_PER_MILLISECOND = 1_000_000n;
export const NS_PER_SECOND = 1_000_000_000n;
export const NS_PER_MINUTE = 60n * NS_PER_SECOND;

const DECIMAL_NS = /^\d+$/;

export class InvalidNanosecondsError extends Error {
  constructor(readonly value: string) {
    super(`invalid nanosecond value: ${value}`);
    this.name = "InvalidNanosecondsError";
  }
}

/** Parse exact decimal-nanosecond text; rejects signs, decimals and exponents. */
export function parseNs(text: string): bigint {
  if (!DECIMAL_NS.test(text)) {
    throw new InvalidNanosecondsError(text);
  }
  return BigInt(text);
}

/** Total parse helper for untrusted inputs (URL search, storage). */
export function tryParseNs(text: unknown): bigint | null {
  if (typeof text !== "string" || !DECIMAL_NS.test(text)) {
    return null;
  }
  return BigInt(text);
}

/** Serialize canonical time for the URL. */
export function formatNsDecimal(ns: bigint): string {
  return ns.toString(10);
}

/**
 * Renderer-local time: a bounded float offset in milliseconds from a viewport
 * origin. The offset is small enough for exact-enough float representation.
 */
export function rendererTimeMs(originNs: bigint, tNs: bigint): number {
  return Number(tNs - originNs) / 1e6;
}

/** Convert a renderer-local millisecond selection back to canonical time. */
export function nsFromRendererTime(originNs: bigint, ms: number): bigint {
  return originNs + BigInt(Math.round(ms * 1e6));
}

/** Format an exact duration deterministically (no locale formatting). */
export function formatDurationNs(ns: bigint): string {
  const negative = ns < 0n;
  const value = negative ? -ns : ns;
  let text: string;
  if (value >= NS_PER_SECOND) {
    text = `${(Number(value) / 1e9).toFixed(3)} s`;
  } else if (value >= NS_PER_MILLISECOND) {
    text = `${(Number(value) / 1e6).toFixed(3)} ms`;
  } else if (value >= NS_PER_MICROSECOND) {
    text = `${(Number(value) / 1e3).toFixed(1)} µs`;
  } else {
    text = `${value} ns`;
  }
  return negative ? `-${text}` : text;
}

/** Format an exact nanosecond timestamp as a monotonic wall-clock-like string. */
export function formatClockNs(ns: bigint): string {
  const negative = ns < 0n;
  const value = negative ? -ns : ns;
  const totalMs = Number(value / NS_PER_MILLISECOND);
  const hours = Math.floor(totalMs / 3_600_000);
  const minutes = Math.floor((totalMs % 3_600_000) / 60_000);
  const seconds = Math.floor((totalMs % 60_000) / 1_000);
  const millis = totalMs % 1_000;
  const pad = (input: number, width: number) => input.toString().padStart(width, "0");
  const prefix = negative ? "-" : "";
  return `${prefix}${pad(hours, 2)}:${pad(minutes, 2)}:${pad(seconds, 2)}.${pad(millis, 3)}`;
}

/** Step a time by a signed number of frames at a nominal rate. */
export function stepFrames(tNs: bigint, frames: number, nominalRateHz: number): bigint {
  if (!Number.isFinite(nominalRateHz) || nominalRateHz <= 0) {
    return tNs;
  }
  const stepNs = NS_PER_SECOND / BigInt(Math.max(1, Math.round(nominalRateHz)));
  return tNs + BigInt(frames) * stepNs;
}

/** Clamp a time into an inclusive canonical range. */
export function clampNs(tNs: bigint, minNs: bigint, maxNs: bigint): bigint {
  if (tNs < minNs) return minNs;
  if (tNs > maxNs) return maxNs;
  return tNs;
}
