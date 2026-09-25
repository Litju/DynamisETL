import { useFrame } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
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
import { FIELD_RENDER_DEPTH_M } from "@/components/matchlab/render-layer-depths";
import { trackingFrameIndexAt } from "@/components/matchlab/frame-buffers";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";

export type ScalarFieldMode = "heatmap" | "contour" | "elevation";

export interface ScalarDomain {
  readonly min: number;
  readonly max: number;
}

export interface ElevationSpec {
  readonly metricId: string;
  readonly measurementClass: string;
  readonly scientificDomain: ScalarDomain;
  readonly units: string;
  readonly elevationTransform: {
    readonly kind: "linear-domain";
    readonly direction: "increasing" | "decreasing";
    readonly meaning: string;
  };
  /** Maximum height above baseline in display metres. It is never pitch/pose height. */
  readonly displayHeightLimitM: number;
  readonly baseline: {
    readonly meaning: "pitch-plane-offset";
    readonly offsetM: number;
  };
  readonly colorDomain: ScalarDomain;
  readonly legendCopy: string;
}

/** Domain is processor metadata, fixed across frames/windows; raw values stay in buffers. */
export interface ScalarFieldSpec {
  readonly metricId: string;
  readonly method: string;
  readonly unit: string;
  readonly measurementClass: string;
  readonly domain: ScalarDomain;
  readonly mode: ScalarFieldMode;
  readonly contourLevels?: readonly number[];
  readonly elevationSpec?: ElevationSpec;
}

export function normalizeScalarValue(value: number, domain: ScalarFieldSpec["domain"]): number {
  if (!Number.isFinite(domain.min) || !Number.isFinite(domain.max) || domain.max <= domain.min) {
    throw new RangeError("Scalar-field domain must be finite and increasing");
  }
  return Math.max(0, Math.min(1, (value - domain.min) / (domain.max - domain.min)));
}

export function elevationHeightM(value: number, spec: ElevationSpec): number {
  const fraction = normalizeScalarValue(value, spec.scientificDomain);
  const directed = spec.elevationTransform.direction === "increasing" ? fraction : 1 - fraction;
  return directed * spec.displayHeightLimitM;
}

function validateElevationSpec(field: ScalarFieldSpec): ElevationSpec {
  const spec = field.elevationSpec;
  if (spec === undefined) throw new RangeError("Analytical elevation requires a metric-specific ElevationSpec");
  if (spec.metricId !== field.metricId || spec.measurementClass !== field.measurementClass || spec.units !== field.unit) {
    throw new RangeError("ElevationSpec metric, measurement class and units must match the scalar field");
  }
  normalizeScalarValue(spec.scientificDomain.min, spec.scientificDomain);
  normalizeScalarValue(spec.colorDomain.min, spec.colorDomain);
  if (!Number.isFinite(spec.displayHeightLimitM) || spec.displayHeightLimitM <= 0) {
    throw new RangeError("Analytical elevation requires a positive display-height limit");
  }
  if (!Number.isFinite(spec.baseline.offsetM) || spec.legendCopy.trim() === "" || spec.elevationTransform.meaning.trim() === "") {
    throw new RangeError("ElevationSpec requires a finite baseline and declared transform/legend semantics");
  }
  return spec;
}

interface SurfaceGrid {
  readonly xValues: readonly number[];
  readonly yValues: readonly number[];
  readonly valuesByPoint: ReadonlyMap<string, number>;
  readonly valid: boolean;
}

function surfaceGridFromBuffers(buffers: TacticalGridWindowBuffers, gridIndex: number): SurfaceGrid {
  const start = buffers.gridOffsets[gridIndex];
  const end = buffers.gridOffsets[gridIndex + 1];
  if (start === undefined || end === undefined || end <= start) return { xValues: [], yValues: [], valuesByPoint: new Map(), valid: false };
  const xValues = [...new Set(Array.from({ length: end - start }, (_, offset) => buffers.positionsXY[(start + offset) * 2]!))].sort((a, b) => a - b);
  const yValues = [...new Set(Array.from({ length: end - start }, (_, offset) => buffers.positionsXY[(start + offset) * 2 + 1]!))].sort((a, b) => a - b);
  const valuesByPoint = new Map<string, number>();
  let unique = true;
  for (let cell = start; cell < end; cell += 1) {
    const key = `${buffers.positionsXY[cell * 2]},${buffers.positionsXY[cell * 2 + 1]}`;
    if (valuesByPoint.has(key)) unique = false;
    valuesByPoint.set(key, buffers.values[cell]!);
  }
  const rectangular = xValues.length >= 2 && yValues.length >= 2 && valuesByPoint.size === xValues.length * yValues.length;
  return { xValues, yValues, valuesByPoint, valid: rectangular && unique };
}

/** Build the current processor grid without smoothing, aggregation, or missing-cell filling. */
export function analyticalElevationGeometryForGrid(
  buffers: TacticalGridWindowBuffers,
  gridIndex: number,
  spec: ElevationSpec,
): BufferGeometry {
  const geometry = new BufferGeometry();
  const grid = surfaceGridFromBuffers(buffers, gridIndex);
  if (!grid.valid) return geometry;
  const vertexCount = grid.xValues.length * grid.yValues.length;
  const positions = new Float32Array(vertexCount * 3);
  const colors = new Float32Array(vertexCount * 3);
  const valueColor = new Color();
  for (let row = 0; row < grid.yValues.length; row += 1) {
    for (let column = 0; column < grid.xValues.length; column += 1) {
      const index = row * grid.xValues.length + column;
      const x = grid.xValues[column]!;
      const y = grid.yValues[row]!;
      const value = grid.valuesByPoint.get(`${x},${y}`);
      if (value === undefined) return geometry;
      const normalized = normalizeScalarValue(value, spec.colorDomain);
      positions.set([x, spec.baseline.offsetM + elevationHeightM(value, spec), -y], index * 3);
      valueColor.setHSL((1 - normalized) * 0.68, 0.82, 0.52);
      colors.set([valueColor.r, valueColor.g, valueColor.b], index * 3);
    }
  }
  const indices: number[] = [];
  for (let row = 0; row < grid.yValues.length - 1; row += 1) {
    for (let column = 0; column < grid.xValues.length - 1; column += 1) {
      const a = row * grid.xValues.length + column;
      const b = a + 1;
      const d = a + grid.xValues.length;
      const c = d + 1;
      if ([a, b, c, d].some((index) => grid.valuesByPoint.get(`${grid.xValues[index % grid.xValues.length]},${grid.yValues[Math.floor(index / grid.xValues.length)]}`) === undefined)) continue;
      indices.push(a, b, c, a, c, d);
    }
  }
  geometry.setAttribute("position", new BufferAttribute(positions, 3));
  geometry.setAttribute("color", new BufferAttribute(colors, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
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
          const contourY = FIELD_RENDER_DEPTH_M.scalarContour;
          output.push(a[0], contourY, -a[1], b[0], contourY, -b[1]);
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

function updateElevationGeometry(
  geometry: BufferGeometry,
  buffers: TacticalGridWindowBuffers,
  gridIndex: number,
  spec: ElevationSpec,
  capacity: number,
): { readonly valid: boolean; readonly vertexCount: number } {
  const grid = surfaceGridFromBuffers(buffers, gridIndex);
  if (!grid.valid) {
    geometry.setDrawRange(0, 0);
    return { valid: false, vertexCount: 0 };
  }
  const vertexCount = grid.xValues.length * grid.yValues.length;
  if (vertexCount > capacity) {
    geometry.setDrawRange(0, 0);
    return { valid: false, vertexCount: 0 };
  }
  let position = geometry.getAttribute("position") as BufferAttribute | undefined;
  let color = geometry.getAttribute("color") as BufferAttribute | undefined;
  if (position === undefined || position.count < vertexCount) {
    position = new BufferAttribute(new Float32Array(capacity * 3), 3);
    color = new BufferAttribute(new Float32Array(capacity * 3), 3);
    geometry.setAttribute("position", position);
    geometry.setAttribute("color", color);
  }
  if (color === undefined || color.count < vertexCount) {
    color = new BufferAttribute(new Float32Array(capacity * 3), 3);
    geometry.setAttribute("color", color);
  }
  const valueColor = new Color();
  for (let row = 0; row < grid.yValues.length; row += 1) {
    for (let column = 0; column < grid.xValues.length; column += 1) {
      const index = row * grid.xValues.length + column;
      const x = grid.xValues[column]!;
      const y = grid.yValues[row]!;
      const value = grid.valuesByPoint.get(`${x},${y}`);
      if (value === undefined) {
        geometry.setDrawRange(0, 0);
        return { valid: false, vertexCount: 0 };
      }
      position.setXYZ(index, x, spec.baseline.offsetM + elevationHeightM(value, spec), -y);
      const normalized = normalizeScalarValue(value, spec.colorDomain);
      valueColor.setHSL((1 - normalized) * 0.68, 0.82, 0.52);
      color.setXYZ(index, valueColor.r, valueColor.g, valueColor.b);
    }
  }
  const indices: number[] = [];
  for (let row = 0; row < grid.yValues.length - 1; row += 1) {
    for (let column = 0; column < grid.xValues.length - 1; column += 1) {
      const a = row * grid.xValues.length + column;
      const b = a + 1;
      const d = a + grid.xValues.length;
      const c = d + 1;
      if ([a, b, c, d].some((index) => grid.valuesByPoint.get(`${grid.xValues[index % grid.xValues.length]},${grid.yValues[Math.floor(index / grid.xValues.length)]}`) === undefined)) continue;
      indices.push(a, b, c, a, c, d);
    }
  }
  position.needsUpdate = true;
  color.needsUpdate = true;
  geometry.setIndex(indices);
  geometry.setDrawRange(0, indices.length);
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return { valid: indices.length > 0, vertexCount: indices.length > 0 ? vertexCount : 0 };
}

function recordElevationUpdate(durationMs: number, cellCount: number, valid: boolean): void {
  if (!import.meta.env.DEV || typeof window === "undefined" ||
    window.localStorage.getItem("dynamis-matchlab-hybrid-benchmark") !== "1") return;
  const benchmarkWindow = window as Window & {
    __dynamisMatchLabScalarSurfaceUpdates?: Array<{ readonly durationMs: number; readonly cellCount: number; readonly valid: boolean }>;
  };
  const samples = benchmarkWindow.__dynamisMatchLabScalarSurfaceUpdates ?? [];
  samples.push({ durationMs, cellCount, valid });
  if (samples.length > 512) samples.shift();
  benchmarkWindow.__dynamisMatchLabScalarSurfaceUpdates = samples;
}

/** Render a processor grid without deriving its colour domain from the current window. */
export function ScalarFieldLayer({
  buffers,
  spec,
  matchFrame,
  maxAgeNs = 0,
  visible = true,
  castShadow = false,
  onElevationUpdate,
}: {
  readonly buffers: TacticalGridWindowBuffers | null;
  readonly spec: ScalarFieldSpec;
  readonly matchFrame: MatchFrameContextValue;
  readonly maxAgeNs?: number;
  readonly visible?: boolean;
  readonly castShadow?: boolean;
  readonly onElevationUpdate?: (state: { readonly valid: boolean; readonly vertexCount: number; readonly gridTimeNs: bigint | null }) => void;
}) {
  normalizeScalarValue(spec.domain.min, spec.domain);
  if (spec.mode === "contour" && (!spec.contourLevels || spec.contourLevels.some((level) => !Number.isFinite(level) || level < spec.domain.min || level > spec.domain.max))) {
    throw new RangeError("Contour levels must lie in the fixed scalar-field domain");
  }
  const elevationSpec = spec.mode === "elevation" ? validateElevationSpec(spec) : null;
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
  const geometry = useMemo(() => new PlaneGeometry(1, 1), []);
  const material = useMemo(
    () => new MeshBasicMaterial({ color: "#ffffff", vertexColors: true, transparent: true, opacity: 0.62, depthWrite: false, side: DoubleSide }),
    [],
  );
  const mesh = useMemo(() => new InstancedMesh(geometry, material, capacity), [capacity, geometry, material]);
  const elevationGeometry = useMemo(() => new BufferGeometry(), []);
  const elevationFrame = useRef<{ buffers: TacticalGridWindowBuffers | null; index: number }>({ buffers: null, index: -1 });
  const elevationMaterial = useMemo(() => new MeshBasicMaterial({ vertexColors: true, side: DoubleSide, transparent: true, opacity: 0.46, depthWrite: false, toneMapped: false }), []);
  useEffect(() => () => {
    geometry.dispose();
    material.dispose();
    elevationGeometry.dispose();
    elevationMaterial.dispose();
  }, [elevationGeometry, elevationMaterial, geometry, material]);
  useFrame(() => {
    const instance = meshRef.current;
    if (spec.mode === "elevation") {
      if (instance !== null) instance.count = 0;
      if (!visible || buffers === null || frameIndex < 0 || elevationSpec === null) {
        elevationGeometry.setDrawRange(0, 0);
        elevationFrame.current = { buffers: null, index: -1 };
        onElevationUpdate?.({ valid: false, vertexCount: 0, gridTimeNs: null });
        return;
      }
      if (elevationFrame.current.buffers === buffers && elevationFrame.current.index === frameIndex) return;
      const startedAt = performance.now();
      const status = updateElevationGeometry(elevationGeometry, buffers, frameIndex, elevationSpec, capacity);
      recordElevationUpdate(performance.now() - startedAt, buffers.gridOffsets[frameIndex + 1]! - buffers.gridOffsets[frameIndex]!, status.valid);
      onElevationUpdate?.({ ...status, gridTimeNs: buffers.gridTimesNs[frameIndex] ?? null });
      elevationFrame.current = { buffers, index: frameIndex };
      return;
    }
    if (instance === null) return;
    elevationGeometry.setDrawRange(0, 0);
    elevationFrame.current = { buffers: null, index: -1 };
    if (buffers === null || frameIndex < 0 || !visible || spec.mode === "contour") {
      instance.count = 0;
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
    instance.count = end - start;
    for (let cell = start; cell < end; cell += 1) {
      const value = buffers.values[cell]!;
      const normalized = normalizeScalarValue(value, spec.domain);
      marker.position.set(
        buffers.positionsXY[cell * 2]!,
        FIELD_RENDER_DEPTH_M.scalarFlat,
        -buffers.positionsXY[cell * 2 + 1]!,
      );
      marker.rotation.set(-Math.PI / 2, 0, 0);
      marker.scale.set(cellWidth, cellHeight, 1);
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
      elevationSpec,
      shadowEnabled: spec.mode === "elevation" && castShadow,
    }}>
      {spec.mode === "elevation" ? (
        <mesh geometry={elevationGeometry} material={elevationMaterial} receiveShadow castShadow={castShadow} onClick={(event) => { event.stopPropagation(); matchFrame.selectTacticalObject(`scalar:${spec.metricId}:elevation:${frameIndex}`); }} />
      ) : spec.mode === "contour" ? (
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
    </group>
  );
}
