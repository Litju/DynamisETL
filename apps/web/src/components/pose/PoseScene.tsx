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
  planarCentre,
  toViewerPoint,
  type CameraPreset,
  type PoseFrame,
  type PoseLandmark,
  type ProcessorOverlays,
  type ViewerPoint,
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

  // Framing follows one observed frame, not the union of many. Pooling 500
  // landmarks across a moving subject inflates the bounding radius with the
  // path they travelled, and the camera then backs off far enough to make the
  // body a speck.
  // The viewer's local origin is fixed to the first observed frame, not
  // recomputed per frame: re-centring every frame would hold the subject still
  // and slide the reference geometry underneath them, which reads as the world
  // moving rather than the athlete.
  const centre = useMemo(() => {
    const firstObserved = frames.find((frame) => frame.observed);
    return planarCentre(firstObserved?.landmarks ?? []);
  }, [frames]);

  const bounds = useMemo(() => {
    const firstObserved = frames.find((frame) => frame.observed);
    return boundsOf(firstObserved?.landmarks ?? []);
  }, [frames]);

  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const { position, target } = cameraFor(preset, bounds);
    // Applied without a transition. A paused scene renders on demand, so an
    // animated move would draw one frame and stop part-way through, leaving
    // the camera short of the preset it was asked for. RES-101 also wants
    // camera changes functional rather than cinematic.
    void controls.setLookAt(
      position[0],
      position[1],
      position[2],
      target[0],
      target[1],
      target[2],
      false,
    );
    invalidate();
  }, [preset, bounds, invalidate]);

  const jointRefs = useRef<Map<string, Mesh>>(new Map());
  // `useFrame` runs outside React's render, so the origin is carried by a ref.
  const centreRef = useRef(centre);
  useEffect(() => {
    centreRef.current = centre;
  }, [centre]);

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
      const [x, y, z] = toViewerPoint(landmark, centreRef.current);
      mesh.position.set(x, y, z);
    }
  });

  const currentTime =
    useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
  const landmarks = landmarksAt(frames, currentTime);
  const byName = new Map(landmarks.map((landmark) => [landmark.jointName, landmark]));

  return (
    <>
      <color attach="background" args={["#12161c"]} />
      <fog attach="fog" args={["#12161c", bounds.radius * 3, bounds.radius * 9]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[2, 4, 3]} intensity={1.1} />
      {/*
        Reference geometry for a *local analytical frame*.

        An infinite ground grid would read as a floor and invite the viewer to
        measure height against it, but this stream's Z is player-centroid
        relative and its axes are the provider's own. The reference is
        therefore a bounded plane sized to the observed landmark cloud and
        placed at the bottom of its bounds — orientation and depth, with no
        claim about absolute height or global position.
      */}
      <Grid
        args={[bounds.radius * 2.6, bounds.radius * 2.6]}
        position={[bounds.center[0], bounds.min[1], bounds.center[2]]}
        cellSize={bounds.radius / 8}
        cellColor="#242c37"
        sectionSize={bounds.radius / 2}
        sectionColor="#33404f"
        fadeDistance={bounds.radius * 14}
        fadeStrength={1.5}
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
          <sphereGeometry args={[selectedJoint === name ? 0.042 : 0.026, 16, 16]} />
          <meshStandardMaterial
            color={selectedJoint === name ? SELECTED_JOINT_COLOR : JOINT_COLOR}
            emissive={selectedJoint === name ? SELECTED_JOINT_COLOR : "#000000"}
            emissiveIntensity={selectedJoint === name ? 0.45 : 0}
            roughness={0.35}
            metalness={0.05}
          />
        </mesh>
      ))}
      {/*
        The selected landmark carries a wireframe shell as well as a larger
        radius and a different hue, so the selection survives a colour-vision
        difference and a greyscale screenshot alike.
      */}
      {selectedJoint !== null && byName.has(selectedJoint) ? (
        <mesh position={toViewerPoint(byName.get(selectedJoint)!, centre)}>
          <sphereGeometry args={[0.07, 16, 16]} />
          <meshBasicMaterial
            color={SELECTED_JOINT_COLOR}
            wireframe
            transparent
            opacity={0.55}
          />
        </mesh>
      ) : null}
      {showErrorRadii
        ? landmarks
            .filter((landmark) => landmark.errorM !== null && landmark.errorM > 0)
            .map((landmark) => (
              <mesh key={`error-${landmark.jointName}`} position={toViewerPoint(landmark, centre)}>
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
            points={[toViewerPoint(start, centre), toViewerPoint(end, centre)]}
            color={SEGMENT_COLOR}
            lineWidth={2.5}
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
        const arc = arcPoints(vertex, first, second, radians, centre);
        if (arc.length < 2) return null;
        return <Line key={angle.name} points={arc} color={ANGLE_COLOR} lineWidth={2} />;
      })}
    </>
  );
}

/**
 * Arc polyline between the two segment directions at the vertex (SLERP).
 *
 * The arc is built in the source frame, where the angle is defined, and each
 * point is mapped into the viewer's frame only for drawing.
 */
export function arcPoints(
  vertex: PoseLandmark,
  first: PoseLandmark,
  second: PoseLandmark,
  radians: number,
  centre: { readonly xM: number; readonly yM: number } = { xM: 0, yM: 0 },
  radius = 0.1,
): ViewerPoint[] {
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
  const points: ViewerPoint[] = [];
  const steps = 20;
  for (let step = 0; step <= steps; step += 1) {
    const t = step / steps;
    const weightU = Math.sin((1 - t) * angle) / sinAngle;
    const weightV = Math.sin(t * angle) / sinAngle;
    const mixed = u.map((value, index) => value * weightU + (v[index] ?? 0) * weightV);
    const norm = Math.hypot(...mixed);
    const normalized = norm === 0 ? [0, 0, 0] : mixed.map((value) => value / norm);
    points.push(
      toViewerPoint(
        {
          xM: vertex.xM + normalized[0]! * radius,
          yM: vertex.yM + normalized[1]! * radius,
          zM: vertex.zM + normalized[2]! * radius,
        },
        centre,
      ),
    );
  }
  return points;
}

export function PoseCanvas({
  frames,
  overlays,
  preset,
  playing,
  showErrorRadii,
  onReady,
}: {
  frames: readonly PoseFrame[];
  overlays: ProcessorOverlays;
  preset: CameraPreset;
  playing: boolean;
  showErrorRadii: boolean;
  onReady?: () => void;
}) {
  return (
    <Canvas
      frameloop={playing ? "always" : "demand"}
      camera={{ fov: 40, near: 0.01, far: 100 }}
      dpr={[1, 2]}
      gl={{ antialias: true }}
      onCreated={() => onReady?.()}
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
