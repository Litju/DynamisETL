/**
 * Exact-frame tactical overlay model.
 *
 * Tactical processors emit one row set per canonical tracking timestamp, so an
 * overlay is looked up by the *exact* frame time the pitch is drawing — never
 * by "nearest row in a window", which can pick geometry from another instant
 * or a display-reduced subset. The one deliberate exception is the Level C
 * influence grid, which the processor samples at most once per
 * `grid_interval_ns`: the most recent grid at or before the frame is used,
 * within a declared maximum age, and its time is returned so it can be stated.
 */

import type {
  TacticalOverlay,
  TacticalRole,
} from "@/components/matchlab/render-types";

export type TacticalRow = Readonly<Record<string, unknown>>;

export interface TacticalFrameIndex {
  readonly byTime: ReadonlyMap<number, readonly TacticalRow[]>;
  /** Distinct canonical times in ascending order. */
  readonly times: readonly number[];
}

export const EMPTY_INDEX: TacticalFrameIndex = { byTime: new Map(), times: [] };

/** Group served rows by their exact canonical time. */
export function indexTacticalRows(rows: readonly TacticalRow[]): TacticalFrameIndex {
  const byTime = new Map<number, TacticalRow[]>();
  for (const row of rows) {
    const time = row["t_rel_ns"];
    if (typeof time !== "number" || !Number.isFinite(time)) continue;
    const bucket = byTime.get(time);
    if (bucket) bucket.push(row);
    else byTime.set(time, [row]);
  }
  const times = [...byTime.keys()].sort((left, right) => left - right);
  return { byTime, times };
}

/** Rows at exactly this canonical time, or none. */
export function rowsAtExactTime(index: TacticalFrameIndex, timeNs: number | null): readonly TacticalRow[] {
  if (timeNs === null) return [];
  return index.byTime.get(timeNs) ?? [];
}

/** The latest row set at or before `timeNs`, no older than `maxAgeNs`. */
export function latestRowsAtOrBefore(
  index: TacticalFrameIndex,
  timeNs: number | null,
  maxAgeNs: number,
): { readonly timeNs: number; readonly rows: readonly TacticalRow[] } | null {
  if (timeNs === null || index.times.length === 0) return null;
  let low = 0;
  let high = index.times.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (index.times[middle]! <= timeNs) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  if (found < 0) return null;
  const time = index.times[found]!;
  if (timeNs - time > maxAgeNs) return null;
  return { timeNs: time, rows: index.byTime.get(time) ?? [] };
}

const EMPTY_POLYGON: readonly [number, number][] = [];
/** Parsed polygons by source string; per-frame drawing never re-parses JSON. */
const polygonCache = new Map<string, readonly [number, number][]>();
const POLYGON_CACHE_LIMIT = 50_000;

export function polygonFromJson(value: unknown): readonly [number, number][] {
  if (typeof value !== "string") return EMPTY_POLYGON;
  const cached = polygonCache.get(value);
  if (cached) return cached;
  const parsed = parsePolygon(value);
  if (polygonCache.size >= POLYGON_CACHE_LIMIT) polygonCache.clear();
  polygonCache.set(value, parsed);
  return parsed;
}

function parsePolygon(value: string): readonly [number, number][] {
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((point): [number, number][] => {
      if (!Array.isArray(point) || point.length < 2) return [];
      const x = point[0];
      const y = point[1];
      return typeof x === "number" && typeof y === "number" && Number.isFinite(x) && Number.isFinite(y)
        ? [[x, y]]
        : [];
    });
  } catch {
    return [];
  }
}

export interface TacticalOverlayAtFrame {
  readonly overlay: TacticalOverlay;
  /** Canonical time of the influence grid drawn, or null when none is drawn. */
  readonly influenceGridTimeNs: number | null;
}

/**
 * Overlay for one drawn frame. `roleOf` maps a provider team id to the same
 * home/away role the entity markers use, so colours can never disagree.
 */
export function tacticalOverlayAt(
  indexes: {
    readonly geometry: TacticalFrameIndex;
    readonly territory: TacticalFrameIndex;
    readonly influence: TacticalFrameIndex;
  },
  frameTimeNs: number | null,
  roleOf: (groupId: string) => TacticalRole,
  influenceMaxAgeNs: number,
): TacticalOverlayAtFrame {
  const hulls = rowsAtExactTime(indexes.geometry, frameTimeNs).flatMap((row) => {
    const groupId = row["group_id"];
    const points = polygonFromJson(row["hull_polygon_json"]);
    return typeof groupId === "string" && points.length >= 2
      ? [{ groupId, role: roleOf(groupId), points }]
      : [];
  });
  const territoryCells = rowsAtExactTime(indexes.territory, frameTimeNs).flatMap((row) => {
    const entityId = row["entity_id"];
    const groupId = row["group_id"];
    const points = polygonFromJson(row["cell_polygon_json"]);
    return typeof entityId === "string" && typeof groupId === "string" && points.length >= 3
      ? [{ entityId, groupId, role: roleOf(groupId), points }]
      : [];
  });
  const grid = latestRowsAtOrBefore(indexes.influence, frameTimeNs, influenceMaxAgeNs);
  const gridRows = grid?.rows ?? [];
  const xValues = [...new Set(gridRows.map((row) => row["x_m"]).filter((value): value is number => typeof value === "number"))].sort((a, b) => a - b);
  const yValues = [...new Set(gridRows.map((row) => row["y_m"]).filter((value): value is number => typeof value === "number"))].sort((a, b) => a - b);
  const widthM = xValues.length > 1 ? Math.abs(xValues[1]! - xValues[0]!) : 5;
  const heightM = yValues.length > 1 ? Math.abs(yValues[1]! - yValues[0]!) : 4;
  const influenceCells = gridRows.flatMap((row) => {
    const x = row["x_m"];
    const y = row["y_m"];
    const groupId = row["owner_group_id"];
    const arrivalTimeS = row["arrival_time_s"];
    return typeof x === "number" && typeof y === "number" && typeof groupId === "string" && typeof arrivalTimeS === "number"
      ? [{ xM: x, yM: y, widthM, heightM, groupId, role: roleOf(groupId), arrivalTimeS }]
      : [];
  });
  return {
    overlay: { hulls, territoryCells, influenceCells },
    influenceGridTimeNs: influenceCells.length > 0 ? (grid?.timeNs ?? null) : null,
  };
}
