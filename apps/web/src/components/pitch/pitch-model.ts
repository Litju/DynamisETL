/**
 * Pitch replay model.
 *
 * Pure, deterministic geometry and frame indexing for the PixiJS renderer:
 * tracking rows become frame-indexed entities, pitch metres map to screen
 * pixels with the pitch Y axis inverted, and detection semantics are preserved
 * (detected ≠ extrapolated) instead of being smoothed or hidden.
 */

export interface PitchGeometry {
  readonly lengthM: number;
  readonly widthM: number;
}

/** SkillCorner pitch is 105 × 68 m with the origin at the centre. */
export const DEFAULT_PITCH: PitchGeometry = { lengthM: 105, widthM: 68 };

export interface Viewport {
  /** World container offset in pixels. */
  readonly offsetX: number;
  readonly offsetY: number;
  /** Pixels per metre. */
  readonly scale: number;
}

export interface EntityFrame {
  readonly objectId: string;
  readonly objectType: string;
  readonly groupId: string | null;
  readonly xM: number;
  readonly yM: number;
  /** Provider detection state; null when the source declares none. */
  readonly detected: boolean | null;
  readonly isBall: boolean;
}

export interface TrackingFrame {
  readonly tRelNs: number;
  readonly entities: readonly EntityFrame[];
}

export interface TrackingRow {
  readonly t_rel_ns?: unknown;
  readonly object_id?: unknown;
  readonly object_type?: unknown;
  readonly group_id?: unknown;
  readonly x_m?: unknown;
  readonly y_m?: unknown;
  readonly is_detected?: unknown;
}

export function isTrackingStream(modality: string): boolean {
  return modality === "tracking";
}

/** Convert pitch metres to screen pixels with Y pointing up the screen. */
export function pitchToScreen(
  xM: number,
  yM: number,
  viewport: Viewport,
  geometry: PitchGeometry = DEFAULT_PITCH,
): { x: number; y: number } {
  void geometry;
  return {
    x: viewport.offsetX + xM * viewport.scale,
    y: viewport.offsetY - yM * viewport.scale,
  };
}

/** Convert a screen pixel back to pitch metres (for direct selection). */
export function screenToPitch(
  xPx: number,
  yPx: number,
  viewport: Viewport,
  geometry: PitchGeometry = DEFAULT_PITCH,
): { xM: number; yM: number } {
  void geometry;
  return {
    xM: (xPx - viewport.offsetX) / viewport.scale,
    yM: (viewport.offsetY - yPx) / viewport.scale,
  };
}

/**
 * Group rows into frames sorted by canonical time. Non-finite or missing
 * coordinates are dropped, never imputed; detection stays explicit.
 */
export function buildFrames(rows: readonly TrackingRow[]): TrackingFrame[] {
  const byTime = new Map<number, EntityFrame[]>();
  for (const row of rows) {
    const t = row.t_rel_ns;
    const x = row.x_m;
    const y = row.y_m;
    const objectId = row.object_id;
    if (typeof t !== "number" || typeof x !== "number" || typeof y !== "number") continue;
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    if (typeof objectId !== "string" || objectId.length === 0) continue;
    const objectType = typeof row.object_type === "string" ? row.object_type : "unknown";
    const entities = byTime.get(t) ?? [];
    entities.push({
      objectId,
      objectType,
      groupId: typeof row.group_id === "string" ? row.group_id : null,
      xM: x,
      yM: y,
      detected: typeof row.is_detected === "boolean" ? row.is_detected : null,
      isBall: objectType === "ball",
    });
    byTime.set(t, entities);
  }
  return Array.from(byTime.entries())
    .sort(([left], [right]) => left - right)
    .map(([tRelNs, entities]) => ({
      tRelNs,
      entities: entities.sort((left, right) => (left.objectId < right.objectId ? -1 : 1)),
    }));
}

/** Index of the frame at or before `tRelNs` (binary search, never extrapolates). */
export function frameIndexAt(frames: readonly TrackingFrame[], tRelNs: bigint): number {
  if (frames.length === 0) return -1;
  const target = Number(tRelNs);
  let low = 0;
  let high = frames.length - 1;
  let result = 0;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (frames[middle]!.tRelNs <= target) {
      result = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return result;
}

/** Entities of the frame nearest to a canonical time. */
export function entitiesAt(
  frames: readonly TrackingFrame[],
  tRelNs: bigint | null,
): readonly EntityFrame[] {
  if (tRelNs === null) return frames[0]?.entities ?? [];
  const index = frameIndexAt(frames, tRelNs);
  return index < 0 ? [] : (frames[index]?.entities ?? []);
}

export interface TrailPoint {
  readonly objectId: string;
  readonly xM: number;
  readonly yM: number;
  readonly detected: boolean | null;
}

/**
 * Trail scoped to one entity and the committed range. The trail is built from
 * observed frames only; extrapolated points are included but flagged so the
 * renderer can dash them.
 */
export function trailForRange(
  frames: readonly TrackingFrame[],
  range: { readonly fromNs: bigint; readonly toNs: bigint } | null,
  objectId: string | null,
): TrailPoint[] {
  if (objectId === null) return [];
  const from = range === null ? null : Number(range.fromNs);
  const to = range === null ? null : Number(range.toNs);
  const trail: TrailPoint[] = [];
  for (const frame of frames) {
    if (from !== null && frame.tRelNs < from) continue;
    if (to !== null && frame.tRelNs > to) continue;
    const entity = frame.entities.find((candidate) => candidate.objectId === objectId);
    if (entity) {
      trail.push({
        objectId: entity.objectId,
        xM: entity.xM,
        yM: entity.yM,
        detected: entity.detected,
      });
    }
  }
  return trail;
}

export interface FrameSummary {
  readonly tRelNs: number;
  readonly players: number;
  readonly extrapolated: number;
  readonly ballDetected: boolean | null;
}

export function summarizeFrame(frame: TrackingFrame | null): FrameSummary | null {
  if (frame === null) return null;
  const ball = frame.entities.find((entity) => entity.isBall) ?? null;
  return {
    tRelNs: frame.tRelNs,
    players: frame.entities.filter((entity) => !entity.isBall).length,
    extrapolated: frame.entities.filter((entity) => entity.detected === false).length,
    ballDetected: ball?.detected ?? null,
  };
}

export type EntityGroup = "home" | "away" | "ball" | "official" | "other";

/**
 * Deterministic team assignment from the provider group ids: the first two
 * distinct group ids (sorted) are home and away; the ball and officials are
 * separate. No identity is fused and no group id is renamed into a claim.
 */
export function assignGroups(
  frames: readonly TrackingFrame[],
): Map<string, EntityGroup> {
  const groupIds = new Set<string>();
  for (const frame of frames) {
    for (const entity of frame.entities) {
      if (entity.groupId !== null) groupIds.add(entity.groupId);
    }
  }
  const ordered = Array.from(groupIds).sort();
  const homeId = ordered[0] ?? null;
  const awayId = ordered[1] ?? null;
  const assignment = new Map<string, EntityGroup>();
  for (const frame of frames) {
    for (const entity of frame.entities) {
      let group: EntityGroup;
      if (entity.isBall) group = "ball";
      else if (entity.objectType === "referee") group = "official";
      else if (homeId !== null && entity.groupId === homeId) group = "home";
      else if (awayId !== null && entity.groupId === awayId) group = "away";
      else group = "other";
      assignment.set(entity.objectId, group);
    }
  }
  return assignment;
}
