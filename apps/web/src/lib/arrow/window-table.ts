/**
 * Renderer-ready window table.
 *
 * One abstraction over both transports: the Arrow path keeps columnar typed
 * arrays, the JSON fallback builds the same shape from records. Neither path
 * creates one generic object per row, and unavailable values stay NaN/null
 * instead of being interpolated.
 */

import type { DecodedWindow } from "@/lib/arrow/decode";
import type { DenseWindow, DenseWindowMeta } from "@/api/types";

export interface WindowTable {
  readonly meta: DenseWindowMeta;
  readonly rowCount: number;
  readonly timeNs: BigInt64Array<ArrayBufferLike>;
  readonly numeric: ReadonlyMap<string, Float64Array>;
  readonly strings: ReadonlyMap<string, string[]>;
  readonly columnOrder: readonly string[];
}

const IDENTITY_COLUMNS = new Set([
  "dataset_id",
  "session_id",
  "trial_id",
  "subject_id",
  "device_id",
  "stream_id",
  "entity_id",
  "object_id",
  "object_type",
  "group_id",
  "sample_index",
  "t_rel_ns",
  "timestamp_utc_ns",
  "nominal_sampling_rate_hz",
  "measurement_class",
  "clock_id",
  "synchronization_spec_id",
  "coordinate_frame_id",
  "skeleton_id",
]);

const TIME_COLUMN = "t_rel_ns";

export function tableFromDecoded(decoded: DecodedWindow, meta: DenseWindowMeta): WindowTable {
  const numeric = new Map<string, Float64Array>();
  const strings = new Map<string, string[]>();
  for (const column of decoded.columns) {
    if (column.numeric) numeric.set(column.name, column.values as Float64Array);
    else strings.set(column.name, column.values as string[]);
  }
  return {
    meta,
    rowCount: decoded.rowCount,
    timeNs: decoded.timeNs,
    numeric,
    strings,
    columnOrder: [TIME_COLUMN, ...decoded.columns.map((column) => column.name)],
  };
}

export function tableFromJson(window: DenseWindow): WindowTable {
  const rows = window.rows;
  const columnOrder = [TIME_COLUMN, ...window.meta.columns.filter((name) => name !== TIME_COLUMN)];
  const timeNs = new BigInt64Array(rows.length);
  const numeric = new Map<string, Float64Array>();
  const strings = new Map<string, string[]>();
  const numericBuffers = new Map<string, Float64Array>();
  const stringBuffers = new Map<string, string[]>();

  for (const name of columnOrder) {
    const sample = rows.find((row) => row[name] !== undefined)?.[name];
    if (name === TIME_COLUMN) continue;
    if (typeof sample === "number" || typeof sample === "bigint") {
      numericBuffers.set(name, new Float64Array(rows.length));
    } else {
      stringBuffers.set(name, new Array<string>(rows.length).fill(""));
    }
  }
  rows.forEach((row, index) => {
    const time = row[TIME_COLUMN];
    if (typeof time === "number") timeNs[index] = BigInt(Math.trunc(time));
    else if (typeof time === "bigint") timeNs[index] = time;
    for (const [name, buffer] of numericBuffers) {
      const value = row[name];
      buffer[index] = typeof value === "number" ? value : Number.NaN;
    }
    for (const [name, buffer] of stringBuffers) {
      const value = row[name];
      buffer[index] = value === null || value === undefined ? "" : String(value);
    }
  });
  for (const [name, buffer] of numericBuffers) numeric.set(name, buffer);
  for (const [name, buffer] of stringBuffers) strings.set(name, buffer);
  return {
    meta: window.meta,
    rowCount: rows.length,
    timeNs,
    numeric,
    strings,
    columnOrder,
  };
}

/** Band pairs produced by the server's display reduction. */
export function bandPairs(table: WindowTable): Array<{ base: string; minKey: string; maxKey: string }> {
  const names = new Set([...table.numeric.keys(), ...table.strings.keys()]);
  const pairs: Array<{ base: string; minKey: string; maxKey: string }> = [];
  for (const name of table.numeric.keys()) {
    if (!name.endsWith("_min")) continue;
    const base = name.slice(0, -"_min".length);
    const maxKey = `${base}_max`;
    if (names.has(maxKey)) pairs.push({ base, minKey: name, maxKey });
  }
  return pairs;
}

/** Numeric measures excluding identity/time columns and envelope members. */
export function measureColumns(table: WindowTable): string[] {
  const bandMembers = new Set(bandPairs(table).flatMap((pair) => [pair.minKey, pair.maxKey]));
  return Array.from(table.numeric.keys()).filter((name) => {
    if (IDENTITY_COLUMNS.has(name) || bandMembers.has(name)) return false;
    return name !== "timestamp_utc_ns";
  });
}

/** Distinct entity keys in row order; empty when the table has no entity column. */
export function entityKeys(table: WindowTable): Array<{ id: string; rows: number[] }> {
  const column = table.strings.get("subject_id") ?? table.strings.get("object_id");
  if (!column) return [];
  const groups = new Map<string, number[]>();
  column.forEach((value, index) => {
    if (value === "") return;
    const rows = groups.get(value) ?? [];
    rows.push(index);
    groups.set(value, rows);
  });
  return Array.from(groups.entries())
    .sort(([left], [right]) => (left < right ? -1 : 1))
    .map(([id, rows]) => ({ id, rows }));
}

export function originNs(table: WindowTable): bigint {
  return table.timeNs[0] ?? BigInt(table.meta.from_ns);
}

export function originMs(
  table: WindowTable,
  index: number,
  origin: bigint,
): number {
  const time = table.timeNs[index] ?? origin;
  return Number(time - origin) / 1e6;
}

export function pointsFor(
  table: WindowTable,
  column: string,
  rows: readonly number[],
  origin: bigint,
): Array<readonly [number, number | null]> {
  const values = table.numeric.get(column);
  if (!values) return [];
  return rows.map((index) => {
    const value = values[index];
    return [originMs(table, index, origin), Number.isFinite(value) ? (value as number) : null] as const;
  });
}

export function bandPointsFor(
  table: WindowTable,
  minKey: string,
  maxKey: string,
  origin: bigint,
): Array<readonly [number, number | null, number | null]> {
  const mins = table.numeric.get(minKey);
  const maxes = table.numeric.get(maxKey);
  if (!mins || !maxes) return [];
  const count = Math.min(mins.length, maxes.length);
  const points: Array<readonly [number, number | null, number | null]> = [];
  for (let index = 0; index < count; index += 1) {
    const minValue = mins[index];
    const maxValue = maxes[index];
    points.push([
      originMs(table, index, origin),
      Number.isFinite(minValue) ? (minValue as number) : null,
      Number.isFinite(maxValue) ? (maxValue as number) : null,
    ]);
  }
  return points;
}
