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
export function extractFrames(rows: readonly PoseRow[]): PoseFrame[] {
  const byTime = new Map<
    number,
    { subjectId: string | null; landmarks: PoseLandmark[]; unavailable: Set<string> }
  >();
  for (const row of rows) {
    const t = row.t_rel_ns;
    if (typeof t !== "number") continue;
    const jointName = row.joint_name;
    if (typeof jointName !== "string" || jointName.length === 0) continue;
    const available = row.is_available === true;
    const x = finite(row.x_m);
    const y = finite(row.y_m);
    const z = finite(row.z_m);
    const entry = byTime.get(t) ?? {
      subjectId: typeof row.subject_id === "string" ? row.subject_id : null,
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
    byTime.set(t, entry);
  }
  return Array.from(byTime.entries())
    .sort(([left], [right]) => left - right)
    .map(([tRelNs, entry]) => ({
      tRelNs,
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

export function frameIndexAt(frames: readonly PoseFrame[], tRelNs: bigint): number {
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

/** Landmarks of the frame at or before the requested time (no interpolation). */
export function landmarksAt(
  frames: readonly PoseFrame[],
  tRelNs: bigint | null,
): readonly PoseLandmark[] {
  if (frames.length === 0) return [];
  const index = tRelNs === null ? 0 : frameIndexAt(frames, tRelNs);
  return index < 0 ? [] : (frames[index]?.landmarks ?? []);
}

export interface Bounds {
  readonly min: readonly [number, number, number];
  readonly max: readonly [number, number, number];
  readonly center: readonly [number, number, number];
  readonly radius: number;
}

/** Bounds of the observed landmarks in the local analytical frame. */
export function boundsOf(landmarks: readonly PoseLandmark[]): Bounds {
  if (landmarks.length === 0) {
    return { min: [0, 0, 0], max: [0, 0, 0], center: [0, 0, 0], radius: 1 };
  }
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let minZ = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  let maxZ = Number.NEGATIVE_INFINITY;
  for (const landmark of landmarks) {
    minX = Math.min(minX, landmark.xM);
    minY = Math.min(minY, landmark.yM);
    minZ = Math.min(minZ, landmark.zM);
    maxX = Math.max(maxX, landmark.xM);
    maxY = Math.max(maxY, landmark.yM);
    maxZ = Math.max(maxZ, landmark.zM);
  }
  const center: [number, number, number] = [
    (minX + maxX) / 2,
    (minY + maxY) / 2,
    (minZ + maxZ) / 2,
  ];
  const radius = Math.max(
    1,
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
  const distance = bounds.radius * 3.2;
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
    return { position: [cx, cy + bounds.radius * 0.4, cz + distance], target: [cx, cy, cz] };
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
