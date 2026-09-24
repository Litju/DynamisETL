import { useEffect, useMemo } from "react";
import { BufferAttribute, BufferGeometry, CylinderGeometry, DoubleSide } from "three";

export interface PitchDimensionsM {
  readonly lengthM: number;
  readonly widthM: number;
}

const LINE_WIDTH_M = 0.1;
const GOAL_WIDTH_M = 7.32;
const GOAL_HEIGHT_M = 2.44;
const GOAL_FRAME_OUTER_WIDTH_M = GOAL_WIDTH_M + LINE_WIDTH_M;
const GOAL_AREA_DEPTH_M = 5.5;
const PENALTY_AREA_DEPTH_M = 16.5;
const PENALTY_SPOT_M = 11;
const CENTER_CIRCLE_RADIUS_M = 9.15;
const CORNER_ARC_RADIUS_M = 1;
const SPOT_RADIUS_M = 0.1;
const LINE_Y = 0.012;

type Point2 = readonly [xM: number, yM: number];

function assertDimensions({ lengthM, widthM }: PitchDimensionsM): void {
  if (!Number.isFinite(lengthM) || !Number.isFinite(widthM) || lengthM <= 0 || widthM <= 0) {
    throw new RangeError("Pitch3D requires positive finite registered pitch dimensions in metres");
  }
}

/** IFAB markings are generated in metres from registered source dimensions. */
export function buildPitchMarkingPositions(dimensions: PitchDimensionsM): Float32Array {
  assertDimensions(dimensions);
  const { lengthM, widthM } = dimensions;
  const halfLength = lengthM / 2;
  const halfWidth = widthM / 2;
  const halfGoal = GOAL_WIDTH_M / 2;
  const points: number[] = [];

  const addPoint = (xM: number, yM: number) => points.push(xM, LINE_Y, -yM);
  const addSegment = (start: Point2, end: Point2) => {
    const ax = start[0];
    const az = -start[1];
    const bx = end[0];
    const bz = -end[1];
    const dx = bx - ax;
    const dz = bz - az;
    const length = Math.hypot(dx, dz);
    if (length === 0) return;
    const half = LINE_WIDTH_M / 2;
    const px = (-dz / length) * half;
    const pz = (dx / length) * half;
    addPoint(ax + px, -az - pz);
    addPoint(ax - px, -az + pz);
    addPoint(bx - px, -bz + pz);
    addPoint(ax + px, -az - pz);
    addPoint(bx - px, -bz + pz);
    addPoint(bx + px, -bz - pz);
  };
  const addPolyline = (path: readonly Point2[], closed = false) => {
    for (let index = 1; index < path.length; index += 1) {
      addSegment(path[index - 1]!, path[index]!);
    }
    if (closed && path.length > 2) addSegment(path[path.length - 1]!, path[0]!);
  };
  const addArc = (
    centerX: number,
    centerY: number,
    radius: number,
    startRadians: number,
    endRadians: number,
    segments: number,
    closed = false,
  ) => {
    const path = Array.from({ length: segments + 1 }, (_, index) => {
      const angle = startRadians + ((endRadians - startRadians) * index) / segments;
      return [centerX + Math.cos(angle) * radius, centerY + Math.sin(angle) * radius] as const;
    });
    addPolyline(path, closed);
  };
  const addArea = (goalX: number, direction: -1 | 1, depth: number, areaHalfWidth: number) => {
    const frontX = goalX - direction * depth;
    addSegment([goalX, -areaHalfWidth], [frontX, -areaHalfWidth]);
    addSegment([frontX, -areaHalfWidth], [frontX, areaHalfWidth]);
    addSegment([frontX, areaHalfWidth], [goalX, areaHalfWidth]);
  };

  addPolyline(
    [
      [-halfLength, -halfWidth],
      [halfLength, -halfWidth],
      [halfLength, halfWidth],
      [-halfLength, halfWidth],
    ],
    true,
  );
  addSegment([0, -halfWidth], [0, halfWidth]);
  addArc(0, 0, CENTER_CIRCLE_RADIUS_M, 0, Math.PI * 2, 96, true);
  addArc(0, 0, SPOT_RADIUS_M, 0, Math.PI * 2, 20, true);

  for (const direction of [-1, 1] as const) {
    const goalX = direction * halfLength;
    const spotX = goalX - direction * PENALTY_SPOT_M;
    addArea(goalX, direction, GOAL_AREA_DEPTH_M, halfGoal + GOAL_AREA_DEPTH_M);
    addArea(goalX, direction, PENALTY_AREA_DEPTH_M, halfGoal + PENALTY_AREA_DEPTH_M);
    addArc(spotX, 0, SPOT_RADIUS_M, 0, Math.PI * 2, 20, true);

    const arcHalfAngle = Math.acos((PENALTY_AREA_DEPTH_M - PENALTY_SPOT_M) / CENTER_CIRCLE_RADIUS_M);
    addArc(
      spotX,
      0,
      CENTER_CIRCLE_RADIUS_M,
      direction < 0 ? -arcHalfAngle : Math.PI - arcHalfAngle,
      direction < 0 ? arcHalfAngle : Math.PI + arcHalfAngle,
      32,
    );
  }

  for (const xSign of [-1, 1] as const) {
    for (const ySign of [-1, 1] as const) {
      const cornerX = xSign * halfLength;
      const cornerY = ySign * halfWidth;
      const path = Array.from({ length: 17 }, (_, index) => {
        const angle = ((Math.PI / 2) * index) / 16;
        return [
          cornerX - xSign * Math.cos(angle) * CORNER_ARC_RADIUS_M,
          cornerY - ySign * Math.sin(angle) * CORNER_ARC_RADIUS_M,
        ] as const;
      });
      addPolyline(path);
    }
  }

  return Float32Array.from(points);
}

function Goal({
  xM,
  postGeometry,
  crossbarGeometry,
}: {
  readonly xM: number;
  readonly postGeometry: CylinderGeometry;
  readonly crossbarGeometry: CylinderGeometry;
}) {
  const halfGoal = GOAL_FRAME_OUTER_WIDTH_M / 2;
  return (
    <group>
      {[-1, 1].map((side) => (
        <mesh
          key={side}
          geometry={postGeometry}
          position={[xM, GOAL_HEIGHT_M / 2, -side * halfGoal]}
          castShadow
        >
          <meshStandardMaterial color="#eef3f1" />
        </mesh>
      ))}
      <mesh
        geometry={crossbarGeometry}
        position={[xM, GOAL_HEIGHT_M, 0]}
        rotation={[Math.PI / 2, 0, 0]}
        castShadow
      >
        <meshStandardMaterial color="#eef3f1" />
      </mesh>
    </group>
  );
}

export function Pitch3D({ dimensions }: { readonly dimensions: PitchDimensionsM }) {
  assertDimensions(dimensions);
  const { lengthM, widthM } = dimensions;
  const positions = useMemo(
    () => buildPitchMarkingPositions({ lengthM, widthM }),
    [lengthM, widthM],
  );
  const lineGeometry = useMemo(() => {
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new BufferAttribute(positions, 3));
    return geometry;
  }, [positions]);
  const postGeometry = useMemo(
    () => new CylinderGeometry(LINE_WIDTH_M / 2, LINE_WIDTH_M / 2, GOAL_HEIGHT_M, 8),
    [],
  );
  const crossbarGeometry = useMemo(
    () => new CylinderGeometry(LINE_WIDTH_M / 2, LINE_WIDTH_M / 2, GOAL_FRAME_OUTER_WIDTH_M, 8),
    [],
  );
  useEffect(
    () => () => {
      lineGeometry.dispose();
      postGeometry.dispose();
      crossbarGeometry.dispose();
    },
    [crossbarGeometry, lineGeometry, postGeometry],
  );

  return (
    <group name="Pitch3D" userData={{ lengthM, widthM }}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[lengthM, widthM]} />
        <meshStandardMaterial color="#194234" roughness={0.94} />
      </mesh>
      <mesh geometry={lineGeometry}>
        <meshBasicMaterial color="#e8eee9" side={DoubleSide} />
      </mesh>
      <Goal xM={-lengthM / 2} postGeometry={postGeometry} crossbarGeometry={crossbarGeometry} />
      <Goal xM={lengthM / 2} postGeometry={postGeometry} crossbarGeometry={crossbarGeometry} />
    </group>
  );
}
