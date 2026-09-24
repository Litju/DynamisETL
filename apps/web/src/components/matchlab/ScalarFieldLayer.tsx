import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  InstancedMesh,
  LineBasicMaterial,
  LineSegments,
  Matrix4,
  MeshBasicMaterial,
  Object3D,
  PlaneGeometry,
} from "three";

import type { TacticalGridWindowBuffers } from "@/components/matchlab/frame-buffers";
import { trackingFrameIndexAt } from "@/components/matchlab/frame-buffers";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";

export type ScalarFieldMode = "heatmap" | "contour" | "elevation";

/** Domain is processor metadata, fixed across frames/windows; raw values stay in buffers. */
export interface ScalarFieldSpec {
  readonly metricId: string;
  readonly method: string;
  readonly unit: string;
  readonly measurementClass: string;
  readonly domain: { readonly min: number; readonly max: number };
  readonly mode: ScalarFieldMode;
  readonly contourLevels?: readonly number[];
  /** Display-only scale for analytical elevation, in metres. */
  readonly elevationScaleM?: number;
}

export function normalizeScalarValue(value: number, domain: ScalarFieldSpec["domain"]): number {
  if (!Number.isFinite(domain.min) || !Number.isFinite(domain.max) || domain.max <= domain.min) {
    throw new RangeError("Scalar-field domain must be finite and increasing");
  }
  return Math.max(0, Math.min(1, (value - domain.min) / (domain.max - domain.min)));
}

/** Marching-squares line segments from one regular processor grid and fixed levels. */
export function contourSegmentsForGrid(
  buffers: TacticalGridWindowBuffers,
  gridIndex: number,
  levels: readonly number[],
): Float32Array {
  const start = buffers.gridOffsets[gridIndex];
  const end = buffers.gridOffsets[gridIndex + 1];
  if (start === undefined || end === undefined || end <= start) return new Float32Array();
  const xValues = [...new Set(Array.from({ length: end - start }, (_, offset) => buffers.positionsXY[(start + offset) * 2]!))].sort((a, b) => a - b);
  const yValues = [...new Set(Array.from({ length: end - start }, (_, offset) => buffers.positionsXY[(start + offset) * 2 + 1]!))].sort((a, b) => a - b);
  const values = new Map<string, number>();
  for (let cell = start; cell < end; cell += 1) {
    values.set(`${buffers.positionsXY[cell * 2]},${buffers.positionsXY[cell * 2 + 1]}`, buffers.values[cell]!);
  }
  const output: number[] = [];
  for (const level of levels) {
    for (let row = 0; row < yValues.length - 1; row += 1) {
      for (let column = 0; column < xValues.length - 1; column += 1) {
        const x0 = xValues[column]!;
        const x1 = xValues[column + 1]!;
        const y0 = yValues[row]!;
        const y1 = yValues[row + 1]!;
        const corners = [
          { x: x0, y: y0, value: values.get(`${x0},${y0}`) },
          { x: x1, y: y0, value: values.get(`${x1},${y0}`) },
          { x: x1, y: y1, value: values.get(`${x1},${y1}`) },
          { x: x0, y: y1, value: values.get(`${x0},${y1}`) },
        ];
        if (corners.some((corner) => corner.value === undefined)) continue;
        const hits: Array<readonly [number, number]> = [];
        for (let edge = 0; edge < 4; edge += 1) {
          const first = corners[edge]!;
          const second = corners[(edge + 1) % 4]!;
          const firstHigh = first.value! >= level;
          const secondHigh = second.value! >= level;
          if (firstHigh === secondHigh) continue;
          const amount = (level - first.value!) / (second.value! - first.value!);
          hits.push([
            first.x + (second.x - first.x) * amount,
            first.y + (second.y - first.y) * amount,
          ]);
        }
        const addSegment = (a: readonly [number, number], b: readonly [number, number]) => {
          output.push(a[0], 0.08, -a[1], b[0], 0.08, -b[1]);
        };
        if (hits.length === 2) addSegment(hits[0]!, hits[1]!);
        else if (hits.length === 4) {
          const centreHigh = corners.reduce((sum, corner) => sum + corner.value!, 0) / 4 >= level;
          if (centreHigh) {
            addSegment(hits[0]!, hits[1]!);
            addSegment(hits[2]!, hits[3]!);
          } else {
            addSegment(hits[0]!, hits[3]!);
            addSegment(hits[1]!, hits[2]!);
          }
        }
      }
    }
  }
  return Float32Array.from(output);
}

function maxGridCells(buffers: TacticalGridWindowBuffers | null): number {
  let maximum = 1;
  if (buffers === null) return maximum;
  for (let grid = 0; grid < buffers.gridTimesNs.length; grid += 1) {
    maximum = Math.max(maximum, buffers.gridOffsets[grid + 1]! - buffers.gridOffsets[grid]!);
  }
  return maximum;
}

/** Render a processor grid without deriving its colour domain from the current window. */
export function ScalarFieldLayer({
  buffers,
  spec,
  matchFrame,
  maxAgeNs = 0,
  visible = true,
}: {
  readonly buffers: TacticalGridWindowBuffers | null;
  readonly spec: ScalarFieldSpec;
  readonly matchFrame: MatchFrameContextValue;
  readonly maxAgeNs?: number;
  readonly visible?: boolean;
}) {
  normalizeScalarValue(spec.domain.min, spec.domain);
  if (spec.mode === "contour" && (!spec.contourLevels || spec.contourLevels.some((level) => !Number.isFinite(level) || level < spec.domain.min || level > spec.domain.max))) {
    throw new RangeError("Contour levels must lie in the fixed scalar-field domain");
  }
  if (spec.mode === "elevation" && (!Number.isFinite(spec.elevationScaleM) || spec.elevationScaleM! <= 0)) {
    throw new RangeError("Analytical elevation requires a positive display scale in metres");
  }
  const frameIndex = useAnalysisStore(useCallback(
    (state) => buffers === null
      ? -1
      : trackingFrameIndexAt(
          buffers.gridTimesNs,
          effectiveTimeNs(state) ?? matchFrame.canonicalTimeNs,
          maxAgeNs,
        ),
    [buffers, matchFrame.canonicalTimeNs, maxAgeNs],
  ));
  const capacity = useMemo(() => maxGridCells(buffers), [buffers]);
  const color = useMemo(() => new Color(), []);
  const marker = useMemo(() => new Object3D(), []);
  const matrix = useMemo(() => new Matrix4(), []);
  const meshRef = useRef<InstancedMesh | null>(null);
  const geometry = useMemo(
    () => spec.mode === "elevation" ? new BoxGeometry(1, 1, 1) : new PlaneGeometry(1, 1),
    [spec.mode],
  );
  const material = useMemo(
    () => new MeshBasicMaterial({ color: "#ffffff", vertexColors: true, transparent: true, opacity: 0.62, depthWrite: false, side: DoubleSide }),
    [],
  );
  const mesh = useMemo(() => new InstancedMesh(geometry, material, capacity), [capacity, geometry, material]);
  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
  }, [geometry, material]);
  useFrame(() => {
    const instance = meshRef.current;
    if (instance === null || buffers === null || frameIndex < 0 || !visible || spec.mode === "contour") {
      if (instance !== null) instance.count = 0;
      return;
    }
    const start = buffers.gridOffsets[frameIndex]!;
    const end = buffers.gridOffsets[frameIndex + 1]!;
    const cellWidthM = buffers.cellWidthM[frameIndex]!;
    const cellHeightM = buffers.cellHeightM[frameIndex]!;
    if (!Number.isFinite(cellWidthM) || !Number.isFinite(cellHeightM) || cellWidthM <= 0 || cellHeightM <= 0) {
      instance.count = 0;
      return;
    }
    const cellWidth = cellWidthM * 0.72;
    const cellHeight = cellHeightM * 0.72;
    const elevationScale = spec.elevationScaleM ?? 0;
    instance.count = end - start;
    for (let cell = start; cell < end; cell += 1) {
      const value = buffers.values[cell]!;
      const normalized = normalizeScalarValue(value, spec.domain);
      const elevation = spec.mode === "elevation" ? Math.max(0.04, normalized * elevationScale) : 0;
      marker.position.set(
        buffers.positionsXY[cell * 2]!,
        spec.mode === "elevation" ? elevation / 2 + 0.025 : 0.025,
        -buffers.positionsXY[cell * 2 + 1]!,
      );
      if (spec.mode !== "elevation") marker.rotation.set(-Math.PI / 2, 0, 0);
      else marker.rotation.set(0, 0, 0);
      marker.scale.set(cellWidth, spec.mode === "elevation" ? elevation : cellHeight, spec.mode === "elevation" ? cellHeight : 1);
      marker.updateMatrix();
      matrix.copy(marker.matrix);
      instance.setMatrixAt(cell - start, matrix);
      color.setHSL((1 - normalized) * 0.68, 0.82, 0.52);
      instance.setColorAt(cell - start, color);
    }
    instance.instanceMatrix.needsUpdate = true;
    if (instance.instanceColor) instance.instanceColor.needsUpdate = true;
  });

  const contourPositions = useMemo(
    () => buffers !== null && frameIndex >= 0 && spec.mode === "contour"
      ? contourSegmentsForGrid(buffers, frameIndex, spec.contourLevels ?? [])
      : new Float32Array(),
    [buffers, frameIndex, spec.contourLevels, spec.mode],
  );
  const contourGeometry = useMemo(() => new BufferGeometry(), []);
  const contourMaterial = useMemo(() => new LineBasicMaterial({ color: "#f4f7f6", transparent: true, opacity: 0.82 }), []);
  const contourLines = useMemo(() => new LineSegments(contourGeometry, contourMaterial), [contourGeometry, contourMaterial]);
  useEffect(() => {
    contourGeometry.setAttribute("position", new BufferAttribute(contourPositions, 3));
    contourGeometry.computeBoundingSphere();
  }, [contourGeometry, contourPositions]);
  useEffect(() => () => {
    contourGeometry.dispose();
    contourMaterial.dispose();
  }, [contourGeometry, contourMaterial]);
  const start = frameIndex >= 0 && buffers !== null ? buffers.gridOffsets[frameIndex]! : 0;
  const objectIdAtInstance = (instanceId: number | undefined) => {
    if (instanceId === undefined || buffers === null || frameIndex < 0) return null;
    const index = start + instanceId;
    const groupIndex = buffers.groupIndexes[index] ?? -1;
    const groupId = groupIndex < 0 ? "all" : buffers.groupIds[groupIndex] ?? "all";
    return `scalar:${spec.metricId}:${groupId}:${buffers.positionsXY[index * 2]}:${buffers.positionsXY[index * 2 + 1]}`;
  };

  return (
    <group name="ScalarFieldLayer" visible={visible && frameIndex >= 0} userData={{
      metricId: spec.metricId,
      method: spec.method,
      unit: spec.unit,
      measurementClass: spec.measurementClass,
      domain: spec.domain,
      displayOnlyElevation: spec.mode === "elevation",
    }}>
      {spec.mode === "contour" ? (
        <primitive object={contourLines} dispose={null} />
      ) : (
        <primitive
          object={mesh}
          ref={meshRef}
          dispose={null}
          onClick={(event: { stopPropagation: () => void; instanceId?: number }) => {
            event.stopPropagation();
            const objectId = objectIdAtInstance(event.instanceId);
            if (objectId !== null) matchFrame.selectTacticalObject(objectId);
          }}
          onPointerOver={(event: { instanceId?: number }) => matchFrame.hoverTacticalObject(objectIdAtInstance(event.instanceId))}
          onPointerOut={() => matchFrame.hoverTacticalObject(null)}
        />
      )}
      {spec.mode === "elevation" ? (
        <Html position={[0, (spec.elevationScaleM ?? 1) + 0.2, 0]} center distanceFactor={110}>
          <span role="note" className="pointer-events-none whitespace-nowrap rounded bg-black/80 px-1.5 py-0.5 text-[9px] text-white">
            NOT PHYSICAL PITCH HEIGHT
          </span>
        </Html>
      ) : null}
    </group>
  );
}
