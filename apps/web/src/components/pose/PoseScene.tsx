import { CameraControls, Grid, Line } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import type { ComponentRef } from "react";
import type { Mesh } from "three";

import {
  angleAt,
  boundsOf,
  cameraFor,
  landmarksAt,
  type CameraPreset,
  type PoseFrame,
  type ProcessorOverlays,
} from "@/components/pose/pose-model";
import { useAnalysisStore } from "@/lib/state/analysis";

export const JOINT_COLOR = "#7fd1e8";
export const SELECTED_JOINT_COLOR = "#ffd166";
export const SEGMENT_COLOR = "#b48ef0";
export const ANGLE_COLOR = "#e884b4";
export const ERROR_RADIUS_COLOR = "#e8a13f";

/**
 * R3F pose scene. Joint glyphs update imperatively in `useFrame` from the
 * shared playhead; React renders the scene graph once per window. Paused frames
 * are rendered on demand. No realistic body mesh and no invented parent tree:
 * processor segments/angles appear only when declared in parameters.
 */
export function PoseScene({
  frames,
  overlays,
  preset,
  showErrorRadii,
}: {
  frames: readonly PoseFrame[];
  overlays: ProcessorOverlays;
  preset: CameraPreset;
  showErrorRadii: boolean;
}) {
  const framesRef = useRef(frames);
  useEffect(() => {
    framesRef.current = frames;
  }, [frames]);
  const { invalidate } = useThree();
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  const controlsRef = useRef<ComponentRef<typeof CameraControls> | null>(null);

  const allNames = useMemo(() => {
    const names = new Set<string>();
    for (const frame of frames.slice(0, 200)) {
      for (const landmark of frame.landmarks) names.add(landmark.jointName);
    }
    return Array.from(names).sort();
  }, [frames]);

  const bounds = useMemo(() => {
    const observed = frames.flatMap((frame) => frame.landmarks);
    return boundsOf(observed.slice(0, 500));
  }, [frames]);

  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const { position, target } = cameraFor(preset, bounds);
    void controls.setLookAt(
      position[0],
      position[1],
      position[2],
      target[0],
      target[1],
      target[2],
      true,
    );
    invalidate();
  }, [preset, bounds, invalidate]);

  const jointRefs = useRef<Map<string, Mesh>>(new Map());

  const setJointRef = useCallback((name: string, mesh: Mesh | null) => {
    if (mesh) jointRefs.current.set(name, mesh);
    else jointRefs.current.delete(name);
  }, []);

  useFrame(() => {
    const time = useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
    const landmarks = new Map(
      landmarksAt(framesRef.current, time).map((landmark) => [landmark.jointName, landmark]),
    );
    for (const [name, mesh] of jointRefs.current) {
      const landmark = landmarks.get(name);
      if (!landmark) {
        mesh.visible = false;
        continue;
      }
      mesh.visible = true;
      mesh.position.set(landmark.xM, landmark.yM, landmark.zM);
    }
  });

  const currentTime =
    useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
  const landmarks = landmarksAt(frames, currentTime);
  const byName = new Map(landmarks.map((landmark) => [landmark.jointName, landmark]));

  return (
    <>
      <color attach="background" args={["#12161c"]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[2, 4, 3]} intensity={1.1} />
      <Grid
        args={[4, 4]}
        cellSize={0.25}
        cellColor="#2a3340"
        sectionSize={1}
        sectionColor="#3d4b5c"
        infiniteGrid
        fadeDistance={12}
      />
      <CameraControls ref={controlsRef} makeDefault />
      {allNames.map((name) => (
        <mesh
          key={name}
          ref={(mesh) => setJointRef(name, mesh)}
          onClick={(event) => {
            event.stopPropagation();
            useAnalysisStore.getState().selectJoint(name);
          }}
          onPointerOver={(event) => {
            event.stopPropagation();
            useAnalysisStore.getState().hoverJoint(name);
          }}
          onPointerOut={() => useAnalysisStore.getState().hoverJoint(null)}
        >
          <sphereGeometry args={[0.022, 12, 12]} />
          <meshStandardMaterial
            color={selectedJoint === name ? SELECTED_JOINT_COLOR : JOINT_COLOR}
            roughness={0.4}
          />
        </mesh>
      ))}
      {showErrorRadii
        ? landmarks
            .filter((landmark) => landmark.errorM !== null && landmark.errorM > 0)
            .map((landmark) => (
              <mesh key={`error-${landmark.jointName}`} position={[landmark.xM, landmark.yM, landmark.zM]}>
                <sphereGeometry args={[landmark.errorM ?? 0, 10, 10]} />
                <meshBasicMaterial color={ERROR_RADIUS_COLOR} transparent opacity={0.12} depthWrite={false} />
              </mesh>
            ))
        : null}
      {overlays.segments.map((segment) => {
        const start = byName.get(segment.startLandmark);
        const end = byName.get(segment.endLandmark);
        if (!start || !end) return null;
        return (
          <Line
            key={segment.name}
            points={[
              [start.xM, start.yM, start.zM],
              [end.xM, end.yM, end.zM],
            ]}
            color={SEGMENT_COLOR}
            lineWidth={2}
          />
        );
      })}
      {overlays.angles.map((angle) => {
        const vertex = byName.get(angle.vertexLandmark);
        const first = byName.get(angle.firstLandmark);
        const second = byName.get(angle.secondLandmark);
        if (!vertex || !first || !second) return null;
        const radians = angleAt(vertex, first, second);
        if (radians === null) return null;
        const arc = arcPoints(vertex, first, second, radians);
        if (arc.length < 2) return null;
        return <Line key={angle.name} points={arc} color={ANGLE_COLOR} lineWidth={2} />;
      })}
    </>
  );
}

/** Arc polyline between the two segment directions at the vertex (SLERP). */
export function arcPoints(
  vertex: { xM: number; yM: number; zM: number },
  first: { xM: number; yM: number; zM: number },
  second: { xM: number; yM: number; zM: number },
  radians: number,
  radius = 0.08,
): Array<[number, number, number]> {
  const toVector = (point: { xM: number; yM: number; zM: number }) => {
    const x = point.xM - vertex.xM;
    const y = point.yM - vertex.yM;
    const z = point.zM - vertex.zM;
    const norm = Math.hypot(x, y, z);
    return norm === 0 ? [0, 0, 0] : [x / norm, y / norm, z / norm];
  };
  const u = toVector(first);
  const v = toVector(second);
  const angle = Math.min(Math.PI - 1e-6, Math.max(1e-6, radians));
  const sinAngle = Math.sin(angle);
  const points: Array<[number, number, number]> = [];
  const steps = 16;
  for (let step = 0; step <= steps; step += 1) {
    const t = step / steps;
    const weightU = Math.sin((1 - t) * angle) / sinAngle;
    const weightV = Math.sin(t * angle) / sinAngle;
    const mixed = u.map((value, index) => value * weightU + (v[index] ?? 0) * weightV);
    const norm = Math.hypot(...mixed);
    const normalized = norm === 0 ? [0, 0, 0] : mixed.map((value) => value / norm);
    points.push([
      vertex.xM + normalized[0]! * radius,
      vertex.yM + normalized[1]! * radius,
      vertex.zM + normalized[2]! * radius,
    ]);
  }
  return points;
}

export function PoseCanvas({
  frames,
  overlays,
  preset,
  playing,
  showErrorRadii,
}: {
  frames: readonly PoseFrame[];
  overlays: ProcessorOverlays;
  preset: CameraPreset;
  playing: boolean;
  showErrorRadii: boolean;
}) {
  return (
    <Canvas
      frameloop={playing ? "always" : "demand"}
      camera={{ fov: 40, near: 0.01, far: 100 }}
      dpr={[1, 2]}
      gl={{ antialias: true }}
    >
      <PoseScene
        frames={frames}
        overlays={overlays}
        preset={preset}
        showErrorRadii={showErrorRadii}
      />
    </Canvas>
  );
}

export default PoseCanvas;
