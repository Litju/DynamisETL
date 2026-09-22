/**
 * Pose viewer model.
 *
 * Source landmarks are source landmarks: no anatomical parent tree is invented,
 * unavailable joints are omitted instead of imputed, and processor-defined
 * segments/angles are rendered only when the versioned processor parameters
 * declare them. Z stays player-centroid-relative; it is never treated as
 * absolute height.
 */

export interface PoseLandmark {
  readonly jointName: string;
  readonly xM: number;
  readonly yM: number;
  readonly zM: number;
  /** Provider p90 predicted error radius, in metres; null when unavailable. */
  readonly errorM: number | null;
}

export interface PoseFrame {
  readonly tRelNs: number;
  readonly subjectId: string | null;
  readonly landmarks: readonly PoseLandmark[];
  /** Joint names the source reported as unavailable at this frame. */
  readonly unavailableJoints: readonly string[];
  /** Frames where the subject has no usable landmarks at all. */
  readonly observed: boolean;
}

export interface PoseSubjectFrames {
  readonly subjectId: string;
  readonly frames: readonly PoseFrame[];
}

export interface PoseRow {
  readonly t_rel_ns?: unknown;
  readonly subject_id?: unknown;
  readonly joint_name?: unknown;
  readonly joint_id?: unknown;
  readonly is_available?: unknown;
  readonly x_m?: unknown;
  readonly y_m?: unknown;
  readonly z_m?: unknown;
  readonly error_m?: unknown;
}

export interface DisplayConnectionDefinition {
  readonly startLandmark: string;
  readonly endLandmark: string;
}

export interface SegmentDefinition {
  readonly name: string;
  readonly startLandmark: string;
  readonly endLandmark: string;
}

export interface AngleDefinition {
  readonly name: string;
  readonly vertexLandmark: string;
  readonly firstLandmark: string;
  readonly secondLandmark: string;
}

export interface ProcessorOverlays {
  readonly segments: readonly SegmentDefinition[];
  readonly angles: readonly AngleDefinition[];
  /** Where the definitions came from; never invented locally. */
  readonly source: "processor_parameters" | "none";
}

export const NO_OVERLAYS: ProcessorOverlays = { segments: [], angles: [], source: "none" };

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Group pose rows into observed frames, dropping unavailable/non-finite joints. */
export function extractFrames(
  rows: readonly PoseRow[],
  subjectId: string | null = null,
): PoseFrame[] {
  const byTime = new Map<
    string,
    { subjectId: string | null; landmarks: PoseLandmark[]; unavailable: Set<string> }
  >();
  for (const row of rows) {
    const t = row.t_rel_ns;
    if (typeof t !== "number") continue;
    const rowSubject =
      typeof row.subject_id === "string"
        ? row.subject_id
        : typeof row.subject_id === "number"
          ? String(row.subject_id)
          : null;
    if (subjectId !== null && rowSubject !== subjectId) continue;
    const jointName = row.joint_name;
    if (typeof jointName !== "string" || jointName.length === 0) continue;
    const available = row.is_available === true;
    const x = finite(row.x_m);
    const y = finite(row.y_m);
    const z = finite(row.z_m);
    const key = `${t}\u0000${rowSubject ?? ""}`;
    const entry = byTime.get(key) ?? {
      subjectId: rowSubject,
      landmarks: [],
      unavailable: new Set<string>(),
    };
    if (available && x !== null && y !== null && z !== null) {
      entry.landmarks.push({
        jointName,
        xM: x,
        yM: y,
        zM: z,
        errorM: finite(row.error_m),
      });
    } else {
      entry.unavailable.add(jointName);
    }
    byTime.set(key, entry);
  }
  return Array.from(byTime.entries())
    .sort(([left], [right]) => {
      const leftTime = Number(left.slice(0, left.indexOf("\u0000")));
      const rightTime = Number(right.slice(0, right.indexOf("\u0000")));
      return leftTime - rightTime || left.localeCompare(right);
    })
    .map(([key, entry]) => ({
      tRelNs: Number(key.slice(0, key.indexOf("\u0000"))),
      subjectId: entry.subjectId,
      landmarks: entry.landmarks.sort((left, right) =>
        left.jointName < right.jointName ? -1 : 1,
      ),
      unavailableJoints: Array.from(entry.unavailable)
        .filter(
          (name) => !entry.landmarks.some((landmark) => landmark.jointName === name),
        )
        .sort(),
      observed: entry.landmarks.length > 0,
    }));
}

/** Group exact frames by their real subject identity for multi-subject display. */
export function groupFramesBySubject(frames: readonly PoseFrame[]): PoseSubjectFrames[] {
  const grouped = new Map<string, PoseFrame[]>();
  for (const frame of frames) {
    const subjectId = frame.subjectId ?? "unscoped";
    const subjectFrames = grouped.get(subjectId) ?? [];
    subjectFrames.push(frame);
    grouped.set(subjectId, subjectFrames);
  }
  return [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([subjectId, subjectFrames]) => ({ subjectId, frames: subjectFrames }));
}

/** Remove display cues that duplicate processor-declared angle geometry. */
export function withoutDuplicateAngles(
  displayAngles: readonly AngleDefinition[],
  processorAngles: readonly AngleDefinition[],
): AngleDefinition[] {
  const key = (angle: AngleDefinition) =>
    `${angle.vertexLandmark}|${[angle.firstLandmark, angle.secondLandmark].sort().join("|")}`;
  const processorKeys = new Set(processorAngles.map(key));
  return displayAngles.filter((angle) => !processorKeys.has(key(angle)));
}

/** Provider display edges whose two endpoints are observed in the frame. */
export function drawableDisplayConnections(
  landmarks: readonly PoseLandmark[],
  connections: readonly DisplayConnectionDefinition[],
): Array<readonly [PoseLandmark, PoseLandmark]> {
  const byName = new Map(landmarks.map((landmark) => [landmark.jointName, landmark]));
  const drawable: Array<readonly [PoseLandmark, PoseLandmark]> = [];
  for (const connection of connections) {
    const start = byName.get(connection.startLandmark);
    const end = byName.get(connection.endLandmark);
    if (start !== undefined && end !== undefined) drawable.push([start, end]);
  }
  return drawable;
}

export function frameIndexAt(frames: readonly PoseFrame[], tRelNs: bigint): number {
  if (frames.length === 0) return -1;
  const target = Number(tRelNs);
  let low = 0;
  let high = frames.length - 1;
  let result = -1;
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

/** Landmarks of the frame at or before the requested time (no interpolation). */
export function landmarksAt(
  frames: readonly PoseFrame[],
  tRelNs: bigint | null,
): readonly PoseLandmark[] {
  if (frames.length === 0) return [];
  const index = tRelNs === null ? 0 : frameIndexAt(frames, tRelNs);
  return index < 0 ? [] : (frames[index]?.landmarks ?? []);
}

/** A point in the viewer's own frame: [right, up, depth], in metres. */
export type ViewerPoint = readonly [number, number, number];

/**
 * Place a source landmark in the viewer's frame.
 *
 * The SkillCorner hybrid frame carries X and Y as pitch-plane metres and Z as
 * a player-centroid-relative vertical. Mapping those axes straight onto the
 * renderer would put the pitch's lateral axis on screen-up and lay the subject
 * on its side, so the viewer applies the explicit rigid rotation
 * R_x(+90°): [source x, source y, source z] → [viewer right, viewer up,
 * viewer depth] = [x, z, −y]. The negative depth keeps the display frame
 * right-handed (determinant +1); it is not a scientific coordinate rewrite.
 *
 * Landmarks are also expressed relative to `centre`, the observed cloud's own
 * centre. Both operations are display-only and change nothing scientific: the
 * processor that produces every served pose metric declares
 * `translation_invariance: relative_vectors_only` and
 * `absolute_height_interpretation: none`, so its angles are computed from
 * relative vectors and carry no absolute position or height to preserve. The
 * viewer states the active frame on screen rather than implying the subject
 * stands on a global pitch plane.
 */
export function toViewerPoint(
  landmark: { readonly xM: number; readonly yM: number; readonly zM: number },
  centre: { readonly xM: number; readonly yM: number },
): ViewerPoint {
  return [landmark.xM - centre.xM, landmark.zM, -(landmark.yM - centre.yM)];
}

/** Pitch-plane centre of the observed landmarks; the viewer's local origin. */
export function planarCentre(
  landmarks: readonly PoseLandmark[],
): { readonly xM: number; readonly yM: number } {
  if (landmarks.length === 0) return { xM: 0, yM: 0 };
  let sumX = 0;
  let sumY = 0;
  for (const landmark of landmarks) {
    sumX += landmark.xM;
    sumY += landmark.yM;
  }
  return { xM: sumX / landmarks.length, yM: sumY / landmarks.length };
}

/**
 * Deterministic display root: midHip, then the observed hip pair, then the
 * observed cloud. A prior root is retained when a frame has no usable root.
 */
export function bodyLocalCentre(
  landmarks: readonly PoseLandmark[],
  fallback: { readonly xM: number; readonly yM: number } | null = null,
): { readonly xM: number; readonly yM: number } {
  const root = landmarks.find((landmark) => landmark.jointName === "midHip");
  if (root) return { xM: root.xM, yM: root.yM };
  const hips = landmarks.filter((landmark) => landmark.jointName === "lHip" || landmark.jointName === "rHip");
  if (hips.length > 0) return planarCentre(hips);
  if (landmarks.length > 0) return planarCentre(landmarks);
  return fallback ?? { xM: 0, yM: 0 };
}

/** Bounds over body-local frames; global travel cancels before fitting. */
export function bodyLocalBounds(frames: readonly PoseFrame[]): Bounds {
  const local: PoseLandmark[] = [];
  for (const frame of frames) {
    if (!frame.observed) continue;
    const centre = bodyLocalCentre(frame.landmarks);
    for (const landmark of frame.landmarks) {
      local.push({
        ...landmark,
        xM: landmark.xM - centre.xM,
        yM: landmark.yM - centre.yM,
      });
    }
  }
  if (local.length < 30) return boundsOf(local, { xM: 0, yM: 0 });
  const [minX, maxX] = robustExtent(local.map((landmark) => landmark.xM));
  const [minY, maxY] = robustExtent(local.map((landmark) => landmark.yM));
  const [minZ, maxZ] = robustExtent(local.map((landmark) => landmark.zM));
  const clipped = local.map((landmark) => ({
    ...landmark,
    xM: clampNumber(landmark.xM, minX, maxX),
    yM: clampNumber(landmark.yM, minY, maxY),
    zM: clampNumber(landmark.zM, minZ, maxZ),
  }));
  return boundsOf(clipped, { xM: 0, yM: 0 });
}

function robustExtent(values: readonly number[]): readonly [number, number] {
  const ordered = [...values].sort((left, right) => left - right);
  const lower = Math.floor((ordered.length - 1) * 0.025);
  const upper = Math.floor((ordered.length - 1) * 0.975);
  return [ordered[lower] ?? 0, ordered[upper] ?? ordered[lower] ?? 0];
}

function clampNumber(value: number, lower: number, upper: number): number {
  return Math.min(upper, Math.max(lower, value));
}

export interface Bounds {
  readonly min: readonly [number, number, number];
  readonly max: readonly [number, number, number];
  readonly center: readonly [number, number, number];
  readonly radius: number;
}

/**
 * Bounds of observed landmarks, in the viewer's frame.
 *
 * The radius is the half-diagonal of the observed cloud with a small floor, so
 * a single-landmark frame still yields a usable camera distance rather than a
 * degenerate one.
 */
export function boundsOf(
  landmarks: readonly PoseLandmark[],
  origin?: { readonly xM: number; readonly yM: number },
): Bounds {
  if (landmarks.length === 0) {
    return { min: [0, 0, 0], max: [0, 0, 0], center: [0, 0, 0], radius: 1 };
  }
  const centre = origin ?? planarCentre(landmarks);
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let minZ = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let maxZ = Number.NEGATIVE_INFINITY;
  for (const landmark of landmarks) {
    const [x, y, z] = toViewerPoint(landmark, centre);
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    minZ = Math.min(minZ, z);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
    maxZ = Math.max(maxZ, z);
  }
  const center: [number, number, number] = [
    (minX + maxX) / 2,
    (minY + maxY) / 2,
    (minZ + maxZ) / 2,
  ];
  const radius = Math.max(
    0.4,
    Math.hypot(maxX - minX, maxY - minY, maxZ - minZ) / 2,
  );
  return { min: [minX, minY, minZ], max: [maxX, maxY, maxZ], center, radius };
}

export type CameraPreset =
  | "free"
  | "front"
  | "rear"
  | "left"
  | "right"
  | "top"
  | "body_local"
  | "reset";

export type PoseCoordinateMode = "body_local" | "match_world";

export type CameraMode =
  | "body_local"
  | "follow_subject"
  | "joint_focus"
  | "world_fixed"
  | "all_subjects"
  | "manual";

export const CAMERA_MODES: readonly CameraMode[] = [
  "body_local",
  "follow_subject",
  "joint_focus",
  "world_fixed",
  "all_subjects",
  "manual",
];

export const CAMERA_PRESETS: readonly CameraPreset[] = [
  "free",
  "front",
  "rear",
  "left",
  "right",
  "top",
  "body_local",
  "reset",
];

/**
 * Camera placement in the local analytical frame. Distances keep the whole
 * landmark cloud visible; presets are functional, never cinematic.
 */
export function cameraFor(
  preset: CameraPreset,
  bounds: Bounds,
): { position: [number, number, number]; target: [number, number, number] } {
  // Close enough that the observed cloud fills the viewport, far enough that a
  // limb swinging outside the first frame's bounds does not leave the view.
  // Leave a measured margin around the cloud: the previous 2.6 factor filled
  // the 40° frustum exactly and clipped the top/bottom of compact skeletons.
  const distance = bounds.radius * 3.6;
  const [cx, cy, cz] = bounds.center;
  const offsets: Record<Exclude<CameraPreset, "free" | "reset">, [number, number, number]> = {
    front: [0, 0, distance],
    rear: [0, 0, -distance],
    left: [-distance, 0, 0],
    right: [distance, 0, 0],
    top: [0, distance, 0],
    body_local: [distance * 0.3, distance * 0.25, distance * 0.9],
  };
  if (preset === "free" || preset === "reset") {
    // A three-quarter view: a straight-on camera flattens the depth axis, and
    // depth is where a markerless estimate is least certain.
    return {
      position: [cx + distance * 0.5, cy + distance * 0.22, cz + distance * 0.82],
      target: [cx, cy, cz],
    };
  }
  const [dx, dy, dz] = offsets[preset];
  return { position: [cx + dx, cy + dy, cz + dz], target: [cx, cy, cz] };
}

/** Parse processor-declared segments/angles from algorithm parameters. */
export function overlaysFromParameters(parameters: unknown): ProcessorOverlays {
  if (typeof parameters !== "object" || parameters === null) return NO_OVERLAYS;
  const record = parameters as { segments?: unknown; angles?: unknown };
  const segments: SegmentDefinition[] = [];
  if (Array.isArray(record.segments)) {
    for (const item of record.segments) {
      if (typeof item !== "object" || item === null) continue;
      const candidate = item as Record<string, unknown>;
      if (
        typeof candidate.name === "string" &&
        typeof candidate.start_landmark === "string" &&
        typeof candidate.end_landmark === "string"
      ) {
        segments.push({
          name: candidate.name,
          startLandmark: candidate.start_landmark,
          endLandmark: candidate.end_landmark,
        });
      }
    }
  }
  const angles: AngleDefinition[] = [];
  if (Array.isArray(record.angles)) {
    for (const item of record.angles) {
      if (typeof item !== "object" || item === null) continue;
      const candidate = item as Record<string, unknown>;
      if (
        typeof candidate.name === "string" &&
        typeof candidate.vertex_landmark === "string" &&
        typeof candidate.first_landmark === "string" &&
        typeof candidate.second_landmark === "string"
      ) {
        angles.push({
          name: candidate.name,
          vertexLandmark: candidate.vertex_landmark,
          firstLandmark: candidate.first_landmark,
          secondLandmark: candidate.second_landmark,
        });
      }
    }
  }
  if (segments.length === 0 && angles.length === 0) return NO_OVERLAYS;
  return { segments, angles, source: "processor_parameters" };
}

/** Angle at `vertex` between vertex→first and vertex→second, in radians. */
export function angleAt(
  vertex: PoseLandmark,
  first: PoseLandmark,
  second: PoseLandmark,
): number | null {
  const u = [first.xM - vertex.xM, first.yM - vertex.yM, first.zM - vertex.zM];
  const v = [second.xM - vertex.xM, second.yM - vertex.yM, second.zM - vertex.zM];
  const normU = Math.hypot(...u);
  const normV = Math.hypot(...v);
  if (normU === 0 || normV === 0) return null;
  const cosine = (u[0]! * v[0]! + u[1]! * v[1]! + u[2]! * v[2]!) / (normU * normV);
  return Math.acos(Math.min(1, Math.max(-1, cosine)));
}

export interface PoseSummary {
  readonly observedLandmarks: number;
  readonly unavailableLandmarks: number;
  readonly landmarksWithError: number;
  readonly meanErrorM: number | null;
}

export function summarizeFrame(frame: PoseFrame | null): PoseSummary {
  if (frame === null) {
    return {
      observedLandmarks: 0,
      unavailableLandmarks: 0,
      landmarksWithError: 0,
      meanErrorM: null,
    };
  }
  const observed = frame.landmarks.length;
  const withError = frame.landmarks.filter((landmark) => landmark.errorM !== null);
  return {
    observedLandmarks: observed,
    unavailableLandmarks: frame.unavailableJoints.length,
    landmarksWithError: withError.length,
    meanErrorM:
      withError.length > 0
        ? withError.reduce((sum, landmark) => sum + (landmark.errorM ?? 0), 0) /
          withError.length
        : null,
  };
}
