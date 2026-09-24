import type { DecodedWindow } from "@/lib/arrow/decode";
import {
  TRACKING_KIND,
  type EventWindowBuffers,
  type PoseWindowBuffers,
  type TacticalGridWindowBuffers,
  type TacticalPolygonWindowBuffers,
  type TrackingWindowBuffers,
} from "@/components/matchlab/frame-buffers";

type ColumnMap = ReadonlyMap<string, DecodedWindow["columns"][number]>;
type PolygonRecord = {
  readonly timeNs: bigint;
  readonly objectId: string;
  readonly groupId: string;
  readonly points: readonly (readonly [number, number])[];
};
type GridRecord = {
  readonly timeNs: bigint;
  readonly xM: number;
  readonly yM: number;
  readonly groupId: string;
  readonly value: number;
};

function columnMap(decoded: DecodedWindow): ColumnMap {
  return new Map(decoded.columns.map((column) => [column.name, column]));
}

function stringAt(columns: ColumnMap, name: string, index: number): string {
  const values = columns.get(name)?.values;
  return Array.isArray(values) ? values[index] ?? "" : "";
}

function numberAt(columns: ColumnMap, name: string, index: number): number {
  const values = columns.get(name)?.values;
  return values instanceof Float64Array ? values[index] ?? Number.NaN : Number.NaN;
}

function kindCode(kind: string): number {
  if (kind === "player") return TRACKING_KIND.player;
  if (kind === "goalkeeper") return TRACKING_KIND.goalkeeper;
  if (kind === "ball") return TRACKING_KIND.ball;
  if (kind === "official" || kind === "referee") return TRACKING_KIND.official;
  return TRACKING_KIND.other;
}

/** Group exact tracking rows and encode identities/quality into transferable columns. */
export function prepareTrackingWindow(decoded: DecodedWindow): TrackingWindowBuffers {
  const columns = columnMap(decoded);
  const byTime = new Map<bigint, number[]>();
  const entityIds = new Set<string>();
  const teamIds = new Set<string>();
  let rowCount = 0;

  for (let row = 0; row < decoded.rowCount; row += 1) {
    const objectId = stringAt(columns, "object_id", row);
    const x = numberAt(columns, "x_m", row);
    const y = numberAt(columns, "y_m", row);
    if (objectId === "" || !Number.isFinite(x) || !Number.isFinite(y)) continue;
    const timeNs = decoded.timeNs[row] ?? 0n;
    const rows = byTime.get(timeNs) ?? [];
    rows.push(row);
    byTime.set(timeNs, rows);
    entityIds.add(objectId);
    const groupId = stringAt(columns, "group_id", row);
    if (groupId !== "") teamIds.add(groupId);
    rowCount += 1;
  }

  const times = [...byTime.keys()].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
  const entityDictionary = [...entityIds].sort();
  const teamDictionary = [...teamIds].sort();
  const entityIndex = new Map(entityDictionary.map((id, index) => [id, index]));
  const teamIndex = new Map(teamDictionary.map((id, index) => [id, index]));
  const frameTimesNs = BigInt64Array.from(times);
  const frameOffsets = new Uint32Array(times.length + 1);
  const entityIndexes = new Uint32Array(rowCount);
  const teamIndexes = new Int32Array(rowCount);
  const positionsXY = new Float32Array(rowCount * 2);
  const objectKinds = new Uint8Array(rowCount);
  const detectionState = new Int8Array(rowCount);
  let outputRow = 0;

  times.forEach((timeNs, frameIndex) => {
    frameOffsets[frameIndex] = outputRow;
    const rows = byTime.get(timeNs)!;
    rows.sort((left, right) => stringAt(columns, "object_id", left).localeCompare(stringAt(columns, "object_id", right)));
    for (const row of rows) {
      const objectId = stringAt(columns, "object_id", row);
      const groupId = stringAt(columns, "group_id", row);
      entityIndexes[outputRow] = entityIndex.get(objectId)!;
      teamIndexes[outputRow] = groupId === "" ? -1 : teamIndex.get(groupId)!;
      positionsXY[outputRow * 2] = numberAt(columns, "x_m", row);
      positionsXY[outputRow * 2 + 1] = numberAt(columns, "y_m", row);
      objectKinds[outputRow] = kindCode(stringAt(columns, "object_type", row));
      const detected = stringAt(columns, "is_detected", row);
      detectionState[outputRow] = detected === "true" ? 1 : detected === "false" ? 0 : -1;
      outputRow += 1;
    }
  });
  frameOffsets[times.length] = outputRow;
  return {
    frameTimesNs,
    frameOffsets,
    entityIds: entityDictionary,
    entityIndexes,
    teamIds: teamDictionary,
    teamIndexes,
    positionsXY,
    objectKinds,
    detectionState,
  };
}

/** Group Pose by participant and exact source timestamp, preserving unavailable joints as masks. */
export function preparePoseWindow(
  decoded: DecodedWindow,
  jointNames: readonly string[],
): PoseWindowBuffers {
  const columns = columnMap(decoded);
  const registeredJoints = jointNames.length > 0
    ? [...jointNames]
    : [...new Set(Array.from({ length: decoded.rowCount }, (_, row) => stringAt(columns, "joint_name", row)).filter(Boolean))].sort();
  if (new Set(registeredJoints).size !== registeredJoints.length) {
    throw new RangeError("Pose preparation requires a unique registered skeleton joint order");
  }
  const jointIndex = new Map(registeredJoints.map((name, index) => [name, index]));
  const bySubject = new Map<string, Map<bigint, Map<number, number>>>();
  const subjects = new Set<string>();

  for (let row = 0; row < decoded.rowCount; row += 1) {
    const subjectId = stringAt(columns, "subject_id", row);
    const name = stringAt(columns, "joint_name", row);
    const index = jointIndex.get(name);
    if (subjectId === "" || index === undefined) continue;
    subjects.add(subjectId);
    const timeNs = decoded.timeNs[row] ?? 0n;
    const frames = bySubject.get(subjectId) ?? new Map<bigint, Map<number, number>>();
    const joints = frames.get(timeNs) ?? new Map<number, number>();
    joints.set(index, row);
    frames.set(timeNs, joints);
    bySubject.set(subjectId, frames);
  }

  const subjectIds = [...subjects].sort();
  const sortedTimes = subjectIds.map((subjectId) =>
    [...(bySubject.get(subjectId)?.keys() ?? [])].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0)),
  );
  const frameCount = sortedTimes.reduce((count, times) => count + times.length, 0);
  const frameTimesNs = new BigInt64Array(frameCount);
  const subjectFrameOffsets = new Uint32Array(subjectIds.length + 1);
  const positionsXYZ = new Float32Array(frameCount * registeredJoints.length * 3).fill(Number.NaN);
  const errorM = new Float32Array(frameCount * registeredJoints.length).fill(Number.NaN);
  const present = new Uint8Array(frameCount * registeredJoints.length);
  const availability = new Uint8Array(frameCount * registeredJoints.length);
  const frameObserved = new Uint8Array(frameCount);
  let frameIndex = 0;

  for (let subjectIndex = 0; subjectIndex < subjectIds.length; subjectIndex += 1) {
    const subjectId = subjectIds[subjectIndex]!;
    const subjectFrames = bySubject.get(subjectId)!;
    subjectFrameOffsets[subjectIndex] = frameIndex;
    for (const timeNs of sortedTimes[subjectIndex]!) {
      frameTimesNs[frameIndex] = timeNs;
      const rows = subjectFrames.get(timeNs)!;
      for (const [landmarkIndex, row] of rows) {
        const rowIndex = frameIndex * registeredJoints.length + landmarkIndex;
        present[rowIndex] = 1;
        if (stringAt(columns, "is_available", row) !== "true") continue;
        const x = numberAt(columns, "x_m", row);
        const y = numberAt(columns, "y_m", row);
        const z = numberAt(columns, "z_m", row);
        if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
        const positionIndex = (frameIndex * registeredJoints.length + landmarkIndex) * 3;
        positionsXYZ[positionIndex] = x;
        positionsXYZ[positionIndex + 1] = y;
        positionsXYZ[positionIndex + 2] = z;
        errorM[rowIndex] = numberAt(columns, "error_m", row);
        availability[rowIndex] = 1;
        frameObserved[frameIndex] = 1;
      }
      frameIndex += 1;
    }
  }
  subjectFrameOffsets[subjectIds.length] = frameIndex;
  return {
    subjectIds,
    jointNames: registeredJoints,
    frameTimesNs,
    subjectFrameOffsets,
    positionsXYZ,
    errorM,
    present,
    availability,
    frameObserved,
  };
}

function polygonPoints(value: string): Array<readonly [number, number]> {
  try {
    const parsed: unknown = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((point): Array<readonly [number, number]> => {
      if (!Array.isArray(point) || point.length < 2) return [];
      const x = point[0];
      const y = point[1];
      return typeof x === "number" && typeof y === "number" && Number.isFinite(x) && Number.isFinite(y)
        ? [[x, y] as const]
        : [];
    });
  } catch {
    return [];
  }
}

/** Parse processor polygon columns in the worker and return canonical-time indexed typed geometry. */
export function prepareTacticalPolygonWindow(
  decoded: DecodedWindow,
  objectColumn: "group_id" | "entity_id",
  polygonColumn: "hull_polygon_json" | "cell_polygon_json",
): TacticalPolygonWindowBuffers {
  const columns = columnMap(decoded);
  const byTime = new Map<bigint, PolygonRecord[]>();
  const objectIds = new Set<string>();
  const groupIds = new Set<string>();
  let polygonCount = 0;
  let pointCount = 0;

  for (let row = 0; row < decoded.rowCount; row += 1) {
    const objectId = stringAt(columns, objectColumn, row);
    const groupId = stringAt(columns, "group_id", row);
    if (objectId === "" || groupId === "") continue;
    const points = polygonPoints(stringAt(columns, polygonColumn, row));
    if (points.length < (polygonColumn === "hull_polygon_json" ? 2 : 3)) continue;
    const timeNs = decoded.timeNs[row] ?? 0n;
    const rows = byTime.get(timeNs) ?? [];
    rows.push({ timeNs, objectId, groupId, points });
    byTime.set(timeNs, rows);
    objectIds.add(objectId);
    groupIds.add(groupId);
    polygonCount += 1;
    pointCount += points.length;
  }

  const times = [...byTime.keys()].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
  const entityIds = [...objectIds].sort();
  const teamIds = [...groupIds].sort();
  const entityIndex = new Map(entityIds.map((id, index) => [id, index]));
  const teamIndex = new Map(teamIds.map((id, index) => [id, index]));
  const frameTimesNs = BigInt64Array.from(times);
  const framePolygonOffsets = new Uint32Array(times.length + 1);
  const polygonPointOffsets = new Uint32Array(polygonCount + 1);
  const positionsXY = new Float32Array(pointCount * 2);
  const objectIndexes = new Uint32Array(polygonCount);
  const groupIndexes = new Int32Array(polygonCount);
  let polygonIndex = 0;
  let pointIndex = 0;
  times.forEach((timeNs, frameIndex) => {
    framePolygonOffsets[frameIndex] = polygonIndex;
    for (const polygon of byTime.get(timeNs)!) {
      objectIndexes[polygonIndex] = entityIndex.get(polygon.objectId)!;
      groupIndexes[polygonIndex] = teamIndex.get(polygon.groupId)!;
      polygonPointOffsets[polygonIndex] = pointIndex;
      for (const [x, y] of polygon.points) {
        positionsXY[pointIndex * 2] = x;
        positionsXY[pointIndex * 2 + 1] = y;
        pointIndex += 1;
      }
      polygonIndex += 1;
    }
  });
  framePolygonOffsets[times.length] = polygonIndex;
  polygonPointOffsets[polygonCount] = pointIndex;
  return {
    frameTimesNs,
    framePolygonOffsets,
    polygonPointOffsets,
    positionsXY,
    objectIds: entityIds,
    objectIndexes,
    groupIds: teamIds,
    groupIndexes,
  };
}

/** Prepare one processor-produced influence grid at each exact grid timestamp. */
export function prepareTacticalGridWindow(decoded: DecodedWindow): TacticalGridWindowBuffers {
  const columns = columnMap(decoded);
  const byTime = new Map<bigint, GridRecord[]>();
  const groupIds = new Set<string>();
  let rowCount = 0;
  for (let row = 0; row < decoded.rowCount; row += 1) {
    const xM = numberAt(columns, "x_m", row);
    const yM = numberAt(columns, "y_m", row);
    const value = numberAt(columns, "arrival_time_s", row);
    const groupId = stringAt(columns, "owner_group_id", row);
    if (!Number.isFinite(xM) || !Number.isFinite(yM) || !Number.isFinite(value) || groupId === "") continue;
    const timeNs = decoded.timeNs[row] ?? 0n;
    const cells = byTime.get(timeNs) ?? [];
    cells.push({ timeNs, xM, yM, groupId, value });
    byTime.set(timeNs, cells);
    groupIds.add(groupId);
    rowCount += 1;
  }

  const times = [...byTime.keys()].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
  const teams = [...groupIds].sort();
  const teamIndex = new Map(teams.map((id, index) => [id, index]));
  const gridTimesNs = BigInt64Array.from(times);
  const gridOffsets = new Uint32Array(times.length + 1);
  const positionsXY = new Float32Array(rowCount * 2);
  const values = new Float32Array(rowCount);
  const groupIndexes = new Int32Array(rowCount);
  const cellWidthM = new Float32Array(times.length);
  const cellHeightM = new Float32Array(times.length);
  let outputRow = 0;

  times.forEach((timeNs, gridIndex) => {
    const cells = byTime.get(timeNs)!;
    gridOffsets[gridIndex] = outputRow;
    const xValues = [...new Set(cells.map((cell) => cell.xM))].sort((left, right) => left - right);
    const yValues = [...new Set(cells.map((cell) => cell.yM))].sort((left, right) => left - right);
    cellWidthM[gridIndex] = xValues.length > 1 ? Math.abs(xValues[1]! - xValues[0]!) : 5;
    cellHeightM[gridIndex] = yValues.length > 1 ? Math.abs(yValues[1]! - yValues[0]!) : 4;
    for (const cell of cells) {
      positionsXY[outputRow * 2] = cell.xM;
      positionsXY[outputRow * 2 + 1] = cell.yM;
      values[outputRow] = cell.value;
      groupIndexes[outputRow] = teamIndex.get(cell.groupId)!;
      outputRow += 1;
    }
  });
  gridOffsets[times.length] = outputRow;
  return { gridTimesNs, gridOffsets, positionsXY, values, groupIds: teams, groupIndexes, cellWidthM, cellHeightM };
}

/** Preserve event identity/type and source time while preparing pitch-position buffers. */
export function prepareEventWindow(decoded: DecodedWindow): EventWindowBuffers {
  const columns = columnMap(decoded);
  const rows: Array<{ timeNs: bigint; eventId: string; eventType: string; subtype: string | null; xM: number; yM: number }> = [];
  for (let index = 0; index < decoded.rowCount; index += 1) {
    const eventId = stringAt(columns, "event_id", index);
    const xM = numberAt(columns, "x_m", index);
    const yM = numberAt(columns, "y_m", index);
    if (eventId === "" || !Number.isFinite(xM) || !Number.isFinite(yM)) continue;
    const eventType = stringAt(columns, "event_type", index) || "event";
    const subtype = stringAt(columns, "event_subtype", index);
    rows.push({
      timeNs: decoded.timeNs[index] ?? 0n,
      eventId,
      eventType,
      subtype: subtype === "" ? null : subtype,
      xM,
      yM,
    });
  }
  return {
    timeNs: BigInt64Array.from(rows.map((row) => row.timeNs)),
    positionsXY: Float32Array.from(rows.flatMap((row) => [row.xM, row.yM])),
    eventIds: rows.map((row) => row.eventId),
    eventTypes: rows.map((row) => row.eventType),
    eventSubtypes: rows.map((row) => row.subtype),
  };
}
