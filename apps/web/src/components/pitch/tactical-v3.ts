import { EMPTY_INDEX, indexTacticalRows, rowsAtExactTime, type TacticalFrameIndex, type TacticalRow } from "@/components/pitch/tactical-overlay";

export interface TacticalV3Frame {
  readonly units: readonly TacticalRow[];
  readonly edges: readonly TacticalRow[];
  readonly triangles: readonly TacticalRow[];
  readonly interactions: readonly TacticalRow[];
  readonly possession: readonly TacticalRow[];
}

export interface TacticalV3Index {
  readonly units: TacticalFrameIndex;
  readonly edges: TacticalFrameIndex;
  readonly triangles: TacticalFrameIndex;
  readonly interactions: TacticalFrameIndex;
  readonly possession: TacticalFrameIndex;
}

export const EMPTY_TACTICAL_V3_INDEX: TacticalV3Index = {
  units: EMPTY_INDEX,
  edges: EMPTY_INDEX,
  triangles: EMPTY_INDEX,
  interactions: EMPTY_INDEX,
  possession: EMPTY_INDEX,
};

export const EMPTY_TACTICAL_V3_FRAME: TacticalV3Frame = {
  units: [],
  edges: [],
  triangles: [],
  interactions: [],
  possession: [],
};

export function indexTacticalV3Frame(input: {
  readonly units?: readonly TacticalRow[];
  readonly edges?: readonly TacticalRow[];
  readonly triangles?: readonly TacticalRow[];
  readonly interactions?: readonly TacticalRow[];
  readonly possession?: readonly TacticalRow[];
}): TacticalV3Index {
  return {
    units: indexTacticalRows(input.units ?? []),
    edges: indexTacticalRows(input.edges ?? []),
    triangles: indexTacticalRows(input.triangles ?? []),
    interactions: indexTacticalRows(input.interactions ?? []),
    possession: indexTacticalRows(input.possession ?? []),
  };
}

export function tacticalV3FrameAt(index: TacticalV3Index, timeNs: bigint | null): TacticalV3Frame {
  const time = timeNs === null ? null : Number(timeNs);
  return {
    units: rowsAtExactTime(index.units, time),
    edges: rowsAtExactTime(index.edges, time),
    triangles: rowsAtExactTime(index.triangles, time),
    interactions: rowsAtExactTime(index.interactions, time),
    possession: rowsAtExactTime(index.possession, time),
  };
}

/** Select processor rows only at the canonical frame the Field is drawing. */
export function tacticalRowsAtFrame(
  rows: readonly TacticalRow[] | undefined,
  timeNs: bigint | null,
): readonly TacticalRow[] {
  if (rows === undefined || timeNs === null) return [];
  const exact = Number(timeNs);
  return rows.filter((row) => row["t_rel_ns"] === exact);
}

/** V3 unit centroids are normalized for analysis; map them back for drawing. */
export function unitPointInSourceFrame(
  row: TacticalRow,
): readonly [number, number] | null {
  const x = row["centroid_x_m"];
  const y = row["centroid_y_m"];
  if (typeof x !== "number" || typeof y !== "number" || !Number.isFinite(x) || !Number.isFinite(y)) {
    return null;
  }
  const flip = row["attacking_direction"] === "right_to_left" ? -1 : 1;
  return [x * flip, y * flip];
}

export function jsonIds(value: unknown): readonly string[] {
  if (typeof value !== "string") return [];
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}
