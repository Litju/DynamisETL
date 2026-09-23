import { CameraControls, Grid } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  DynamicDrawUsage,
  InstancedMesh,
  LineBasicMaterial,
  LineSegments,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  Quaternion,
  RingGeometry,
  SphereGeometry,
  Vector3,
} from "three";

import {
  angleAt,
  bodyLocalBounds,
  bodyLocalCentre,
  boundsOf,
  cameraFor,
  landmarksAt,
  toViewerPoint,
  type AngleDefinition,
  type CameraMode,
  type CameraPreset,
  type DisplayConnectionDefinition,
  type PoseFrame,
  type PoseLandmark,
  type PoseSubjectFrames,
  type ProcessorOverlays,
  type PoseCoordinateMode,
  type ViewerPoint,
  withoutDuplicateAngles,
} from "@/components/pose/pose-model";
import { useAnalysisStore } from "@/lib/state/analysis";

export const JOINT_COLOR = "#9fe3f2";
/** Non-focus subjects in the all-subject world: present, but subordinate. */
export const CONTEXT_SUBJECT_COLOR = "#56616d";
export const SELECTED_JOINT_COLOR = "#ffd166";
export const PROVIDER_SKELETON_COLOR = "#86b7cc";
export const TORSO_CUE_COLOR = "#9dc6d4";
export const FOOT_CONTACT_CUE_COLOR = "#b9dbe5";
export const HEAD_NECK_CUE_COLOR = "#b9dbe5";
export const ARTICULATION_ANGLE_CUE_COLOR = "#d9b7e8";
export const SEGMENT_COLOR = "#b48ef0";
export const ANGLE_COLOR = "#e884b4";
export const ERROR_RADIUS_COLOR = "#e8a13f";

const TORSO_CUE_CONNECTIONS: readonly DisplayConnectionDefinition[] = [
  { startLandmark: "lShoulder", endLandmark: "lHip" },
  { startLandmark: "rShoulder", endLandmark: "rHip" },
];
const FOOT_CONTACT_CUE_CONNECTIONS: readonly DisplayConnectionDefinition[] = [
  { startLandmark: "lHeel", endLandmark: "lBigToe" },
  { startLandmark: "lHeel", endLandmark: "lSmallToe" },
  { startLandmark: "lAnkle", endLandmark: "lSmallToe" },
  { startLandmark: "rHeel", endLandmark: "rBigToe" },
  { startLandmark: "rHeel", endLandmark: "rSmallToe" },
  { startLandmark: "rAnkle", endLandmark: "rSmallToe" },
];
const HAND_CONTACT_CUE_CONNECTIONS: readonly DisplayConnectionDefinition[] = [
  { startLandmark: "lThumb", endLandmark: "lPinky" },
  { startLandmark: "rThumb", endLandmark: "rPinky" },
];
const HEAD_NECK_CUE_CONNECTIONS: readonly DisplayConnectionDefinition[] = [
  { startLandmark: "lEar", endLandmark: "neck" },
  { startLandmark: "rEar", endLandmark: "neck" },
  { startLandmark: "lEar", endLandmark: "rEar" },
];
const ARTICULATION_ANGLE_CUES: readonly AngleDefinition[] = [
  { name: "head_orientation", vertexLandmark: "nose", firstLandmark: "lEar", secondLandmark: "rEar" },
  { name: "neck_orientation", vertexLandmark: "neck", firstLandmark: "nose", secondLandmark: "midHip" },
  { name: "left_shoulder", vertexLandmark: "lShoulder", firstLandmark: "neck", secondLandmark: "lElbow" },
  { name: "right_shoulder", vertexLandmark: "rShoulder", firstLandmark: "neck", secondLandmark: "rElbow" },
  { name: "left_elbow", vertexLandmark: "lElbow", firstLandmark: "lShoulder", secondLandmark: "lWrist" },
  { name: "right_elbow", vertexLandmark: "rElbow", firstLandmark: "rShoulder", secondLandmark: "rWrist" },
  { name: "left_wrist", vertexLandmark: "lWrist", firstLandmark: "lElbow", secondLandmark: "lPinky" },
  { name: "right_wrist", vertexLandmark: "rWrist", firstLandmark: "rElbow", secondLandmark: "rPinky" },
  { name: "left_hip", vertexLandmark: "lHip", firstLandmark: "lShoulder", secondLandmark: "lKnee" },
  { name: "right_hip", vertexLandmark: "rHip", firstLandmark: "rShoulder", secondLandmark: "rKnee" },
  { name: "left_knee", vertexLandmark: "lKnee", firstLandmark: "lHip", secondLandmark: "lAnkle" },
  { name: "right_knee", vertexLandmark: "rKnee", firstLandmark: "rHip", secondLandmark: "rAnkle" },
  { name: "left_ankle", vertexLandmark: "lAnkle", firstLandmark: "lKnee", secondLandmark: "lBigToe" },
  { name: "right_ankle", vertexLandmark: "rAnkle", firstLandmark: "rKnee", secondLandmark: "rBigToe" },
];

export interface PoseSceneProps {
  readonly frames: readonly PoseFrame[];
  readonly subjectFrames: readonly PoseSubjectFrames[];
  readonly allSubjects: boolean;
  readonly overlays: ProcessorOverlays;
  readonly providerConnections: readonly DisplayConnectionDefinition[];
  readonly preset: CameraPreset;
  readonly cameraMode: CameraMode;
  readonly coordinateMode: PoseCoordinateMode;
  readonly onManualCamera?: () => void;
  readonly showProviderSkeleton: boolean;
  readonly showTorsoCue: boolean;
  readonly showFootContact: boolean;
  readonly showHandContact: boolean;
  readonly showHeadNeck: boolean;
  readonly showArticulationAngles: boolean;
  readonly showSegments: boolean;
  readonly showAngles: boolean;
  readonly showErrorRadii: boolean;
  /** The Pose subject (URL authority); the focus of the all-subject world. */
  readonly selectedSubjectId?: string | null;
  /** Clicking a subject in the all-subject world selects it as the subject. */
  readonly onSelectSubject?: (subjectId: string) => void;
}

interface LandmarkDescriptor {
  readonly subjectId: string;
  readonly subjectIndex: number;
  readonly jointName: string;
}

interface CurrentSubjectFrame {
  readonly landmarks: ReadonlyMap<string, PoseLandmark>;
  readonly centre: { readonly xM: number; readonly yM: number };
}

type CurrentLandmarks = readonly CurrentSubjectFrame[];

export function PoseScene(props: PoseSceneProps) {
  const subjects = useMemo(
    () => props.allSubjects ? props.subjectFrames : [{ subjectId: props.frames[0]?.subjectId ?? "selected", frames: props.frames }],
    [props.allSubjects, props.frames, props.subjectFrames],
  );
  const firstLandmarks = useMemo(
    () => subjects.flatMap((subject) => subject.frames.find((frame) => frame.observed)?.landmarks ?? []),
    [subjects],
  );
  const calculatedBounds = useMemo(() => {
    if (props.coordinateMode === "body_local") {
      return bodyLocalBounds(subjects.flatMap((subject) => subject.frames));
    }
    return boundsOf(firstLandmarks, WORLD_ORIGIN);
  }, [firstLandmarks, props.coordinateMode, subjects]);
  const sourceKey = `${props.coordinateMode}:${subjects.map((subject) => subject.subjectId).join(",")}`;
  // Deliberately retain the first bounds for one coordinate/subject context;
  // chunk handoff must not refit a trajectory-derived camera.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableBounds = useMemo(() => calculatedBounds, [sourceKey]);
  return <PoseStage {...props} subjects={subjects} bounds={stableBounds} />;
}

const WORLD_ORIGIN = { xM: 0, yM: 0 } as const;

function PoseStage({ subjects, bounds, ...props }: PoseSceneProps & {
  readonly subjects: readonly PoseSubjectFrames[];
  readonly bounds: ReturnType<typeof boundsOf>;
}) {
  const { invalidate, setFrameloop } = useThree();
  const playing = useAnalysisStore((state) => state.playing);
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  const { cameraMode, onManualCamera } = props;
  const controlsRef = useRef<React.ElementRef<typeof CameraControls> | null>(null);
  const followTarget = useRef(new Vector3());
  const hasFollowTarget = useRef(false);
  useEffect(() => useAnalysisStore.subscribe((state, previous) => {
    if (state.playheadNs !== previous.playheadNs || state.playing !== previous.playing) invalidate();
  }), [invalidate]);
  useEffect(() => {
    setFrameloop(playing ? "always" : "demand");
    invalidate();
  }, [invalidate, playing, setFrameloop]);
  // Clip planes follow the scene scale: a body-local skeleton is ~1 m, the
  // all-subject world spans the pitch; a fixed 100 m far plane clipped it.
  const camera = useThree((state) => state.camera);
  useEffect(() => {
    if (!("isPerspectiveCamera" in camera)) return;
    camera.near = Math.max(0.005, bounds.radius / 400);
    camera.far = Math.max(50, bounds.radius * 40);
    camera.updateProjectionMatrix();
    invalidate();
  }, [bounds.radius, camera, invalidate]);
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls || cameraMode === "manual") return;
    const { position, target } = cameraFor("reset", bounds);
    void controls.setLookAt(position[0], position[1], position[2], target[0], target[1], target[2], false);
    invalidate();
    hasFollowTarget.current = false;
  }, [bounds, cameraMode, invalidate]);
  useFrame((_state, delta) => {
    if (cameraMode !== "follow_subject" && cameraMode !== "joint_focus") return;
    const subject = subjects[0];
    if (!subject) return;
    const time = useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
    const landmarks = landmarksAt(subject.frames, time);
    let desired: readonly [number, number, number] | null = null;
    const centre = props.coordinateMode === "body_local" ? bodyLocalCentre(landmarks) : WORLD_ORIGIN;
    if (cameraMode === "follow_subject") {
      const root = props.coordinateMode === "body_local" ? WORLD_ORIGIN : bodyLocalCentre(landmarks);
      desired = [root.xM, 0, -root.yM];
    } else if (selectedJoint !== null) {
      const joint = landmarks.find((landmark) => landmark.jointName === selectedJoint);
      if (joint) desired = toViewerPoint(joint, centre);
    }
    if (desired === null) return;
    const target = followTarget.current;
    if (!hasFollowTarget.current) {
      target.set(desired[0], desired[1], desired[2]);
      hasFollowTarget.current = true;
    }
    const desiredVector = new Vector3(desired[0], desired[1], desired[2]);
    if (target.distanceTo(desiredVector) > Math.max(0.1, bounds.radius * 0.2)) {
      target.lerp(desiredVector, Math.min(1, Math.max(0, delta) * 6));
      controlsRef.current?.setTarget(target.x, target.y, target.z, false);
      invalidate();
    }
  });
  const handleControlStart = useCallback(() => {
    if (cameraMode !== "manual") onManualCamera?.();
  }, [cameraMode, onManualCamera]);
  return (
    <>
      <color attach="background" args={["#12161c"]} />
      {/* The camera sits ~3.6 radii from the subject; fog begins beyond the
          observed cloud so it only recedes the far grid, never the skeleton. */}
      <fog attach="fog" args={["#12161c", bounds.radius * 6, bounds.radius * 18]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[2, 4, 3]} intensity={1.1} />
      <Grid args={[bounds.radius * 2.6, bounds.radius * 2.6]} position={[bounds.center[0], bounds.min[1], bounds.center[2]]} cellSize={bounds.radius / 8} cellColor="#242c37" sectionSize={bounds.radius / 2} sectionColor="#33404f" fadeDistance={bounds.radius * 14} fadeStrength={1.5} />
      <CameraControls ref={controlsRef} makeDefault onStart={handleControlStart} />
      <PoseHotPath subjects={subjects} sceneRadius={bounds.radius} {...props} />
    </>
  );
}

function PoseHotPath({ subjects, overlays, providerConnections, showProviderSkeleton, showTorsoCue, showFootContact, showHandContact, showHeadNeck, showArticulationAngles, showSegments, showAngles, showErrorRadii, coordinateMode, selectedSubjectId = null, onSelectSubject, sceneRadius }: PoseSceneProps & {
  readonly subjects: readonly PoseSubjectFrames[];
  readonly sceneRadius: number;
}) {
  // In the all-subject world the camera frames the whole group, so a 3 cm
  // glyph is sub-pixel; joints scale with the scene so every figure stays
  // readable. A single subject keeps its true glyph size.
  const glyphScale = subjects.length > 1 ? Math.min(4, Math.max(1, sceneRadius / 6)) : 1;
  const descriptors = useMemo<LandmarkDescriptor[]>(() => subjects.flatMap((subject, subjectIndex) => {
    const names = new Set<string>();
    for (const frame of subject.frames.slice(0, 200)) for (const landmark of frame.landmarks) names.add(landmark.jointName);
    return [...names].sort().map((jointName) => ({ subjectId: subject.subjectId, subjectIndex, jointName }));
  }), [subjects]);
  const jointMesh = useInstancedGlyph(descriptors.length, false);
  const errorMesh = useInstancedGlyph(descriptors.length, true);
  const currentRef = useRef<CurrentLandmarks>([]);
  const centresRef = useRef<Array<{ readonly xM: number; readonly yM: number }>>([]);
  const identity = useMemo(() => new Quaternion(), []);
  const matrix = useMemo(() => new Matrix4(), []);
  const position = useMemo(() => new Vector3(), []);
  const scale = useMemo(() => new Vector3(), []);
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  // The focus subject: the only one in single-subject scope; otherwise the
  // URL-selected Pose subject (never the Field entity selection).
  const focusIndex = subjects.length <= 1
    ? 0
    : Math.max(0, subjects.findIndex((subject) => subject.subjectId === selectedSubjectId));
  const focusIndices = useMemo(() => [focusIndex], [focusIndex]);
  const contextIndices = useMemo(
    () => subjects.map((_subject, index) => index).filter((index) => index !== focusIndex),
    [focusIndex, subjects],
  );
  const palette = useMemo(() => ({
    joint: new Color(JOINT_COLOR),
    selected: new Color(SELECTED_JOINT_COLOR),
    context: new Color(CONTEXT_SUBJECT_COLOR),
    error: new Color(ERROR_RADIUS_COLOR),
  }), []);
  const focusRing = useMemo(() => {
    const ring = new Mesh(
      new RingGeometry(0.75, 1, 48),
      new MeshBasicMaterial({ color: SELECTED_JOINT_COLOR, transparent: true, opacity: 0.85, depthWrite: false }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.visible = false;
    return ring;
  }, []);
  useEffect(() => () => {
    focusRing.geometry.dispose();
    (focusRing.material as MeshBasicMaterial).dispose();
  }, [focusRing]);
  const articulationAngles = useMemo(() => withoutDuplicateAngles(ARTICULATION_ANGLE_CUES, overlays.angles), [overlays.angles]);
  useFrame(() => {
    const time = useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
    const current = subjects.map((subject, subjectIndex) => {
      const byName = new Map<string, PoseLandmark>();
      for (const landmark of landmarksAt(subject.frames, time)) byName.set(landmark.jointName, landmark);
      const centre = coordinateMode === "body_local"
        ? bodyLocalCentre([...byName.values()], centresRef.current[subjectIndex] ?? null)
        : WORLD_ORIGIN;
      centresRef.current[subjectIndex] = centre;
      return { landmarks: byName, centre };
    });
    currentRef.current = current;
    for (let index = 0; index < descriptors.length; index += 1) {
      const descriptor = descriptors[index]!;
      const landmark = current[descriptor.subjectIndex]?.landmarks.get(descriptor.jointName);
      const visible = landmark !== undefined;
      const point = visible ? toViewerPoint(landmark, current[descriptor.subjectIndex]?.centre ?? WORLD_ORIGIN) : [0, 0, 0] as const;
      const focus = descriptor.subjectIndex === focusIndex;
      const selected = focus && descriptor.jointName === selectedJoint;
      position.set(point[0], point[1], point[2]);
      const jointScale = visible ? glyphScale * (selected ? 1.8 : focus ? 1.25 : 0.8) : 0;
      scale.set(jointScale, jointScale, jointScale);
      matrix.compose(position, identity, scale);
      jointMesh.setMatrixAt(index, matrix);
      jointMesh.setColorAt(index, selected ? palette.selected : focus ? palette.joint : palette.context);
      // Error radii belong to the focus subject only; in the all-subject world
      // they would bury every neighbour under translucent spheres.
      const errorScale = focus && showErrorRadii && visible && landmark.errorM !== null && landmark.errorM > 0 ? landmark.errorM : 0;
      scale.set(errorScale, errorScale, errorScale);
      matrix.compose(position, identity, scale);
      errorMesh.setMatrixAt(index, matrix);
      errorMesh.setColorAt(index, palette.error);
    }
    // Focus marker: a ground ring under the selected subject in the
    // all-subject world, so the focus is unambiguous at group scale.
    const focus = current[focusIndex];
    if (subjects.length > 1 && focus && focus.landmarks.size > 0) {
      const landmarks = [...focus.landmarks.values()];
      const root = bodyLocalCentre(landmarks);
      const floor = Math.min(...landmarks.map((landmark) => landmark.zM));
      focusRing.position.set(root.xM - focus.centre.xM, floor, -(root.yM - focus.centre.yM));
      focusRing.scale.setScalar(Math.max(0.6, sceneRadius / 18));
      focusRing.visible = true;
    } else {
      focusRing.visible = false;
    }
    jointMesh.instanceMatrix.needsUpdate = true;
    errorMesh.instanceMatrix.needsUpdate = true;
    if (jointMesh.instanceColor) jointMesh.instanceColor.needsUpdate = true;
    if (errorMesh.instanceColor) errorMesh.instanceColor.needsUpdate = true;
  });
  const handleJointClick = useCallback((event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    const descriptor = event.instanceId === undefined ? undefined : descriptors[event.instanceId];
    if (!descriptor) return;
    if (subjects.length > 1 && descriptor.subjectIndex !== focusIndex) {
      onSelectSubject?.(descriptor.subjectId);
      return;
    }
    useAnalysisStore.getState().selectJoint(descriptor.jointName);
  }, [descriptors, focusIndex, onSelectSubject, subjects.length]);
  const handleJointHover = useCallback((event: ThreeEvent<PointerEvent>) => {
    const descriptor = event.instanceId === undefined ? undefined : descriptors[event.instanceId];
    useAnalysisStore.getState().hoverJoint(descriptor?.jointName ?? null);
    if (subjects.length > 1) useAnalysisStore.getState().hoverEntity(descriptor?.subjectId ?? null);
  }, [descriptors, subjects.length]);
  const processorSegments = showSegments ? overlays.segments.map((segment) => ({ startLandmark: segment.startLandmark, endLandmark: segment.endLandmark })) : [];
  return (
    <>
      <primitive object={jointMesh} onClick={handleJointClick} onPointerOver={handleJointHover} onPointerOut={() => { useAnalysisStore.getState().hoverJoint(null); useAnalysisStore.getState().hoverEntity(null); }} />
      <primitive object={errorMesh} />
      <primitive object={focusRing} />
      {showProviderSkeleton ? <BatchedSegments indices={focusIndices} currentRef={currentRef} connections={providerConnections} color={PROVIDER_SKELETON_COLOR} /> : null}
      {showProviderSkeleton && contextIndices.length > 0 ? <BatchedSegments indices={contextIndices} currentRef={currentRef} connections={providerConnections} color={CONTEXT_SUBJECT_COLOR} /> : null}
      {showTorsoCue ? <BatchedSegments indices={focusIndices} currentRef={currentRef} connections={TORSO_CUE_CONNECTIONS} color={TORSO_CUE_COLOR} /> : null}
      {showFootContact ? <BatchedSegments indices={focusIndices} currentRef={currentRef} connections={FOOT_CONTACT_CUE_CONNECTIONS} color={FOOT_CONTACT_CUE_COLOR} /> : null}
      {showHandContact ? <BatchedSegments indices={focusIndices} currentRef={currentRef} connections={HAND_CONTACT_CUE_CONNECTIONS} color={FOOT_CONTACT_CUE_COLOR} /> : null}
      {showHeadNeck ? <BatchedSegments indices={focusIndices} currentRef={currentRef} connections={HEAD_NECK_CUE_CONNECTIONS} color={HEAD_NECK_CUE_COLOR} /> : null}
      {processorSegments.length > 0 ? <BatchedSegments indices={focusIndices} currentRef={currentRef} connections={processorSegments} color={SEGMENT_COLOR} /> : null}
      {showAngles && overlays.angles.length > 0 ? <BatchedAngles indices={focusIndices} currentRef={currentRef} definitions={overlays.angles} color={ANGLE_COLOR} /> : null}
      {showArticulationAngles && articulationAngles.length > 0 ? <BatchedAngles indices={focusIndices} currentRef={currentRef} definitions={articulationAngles} color={ARTICULATION_ANGLE_CUE_COLOR} articulation /> : null}
    </>
  );
}

function useInstancedGlyph(count: number, error: boolean): InstancedMesh {
  const mesh = useMemo(() => {
    const geometry = new SphereGeometry(error ? 1 : 0.03, error ? 12 : 14, error ? 10 : 12);
    // Instance colours come from `instanceColor`; `vertexColors` would also
    // multiply by a geometry colour attribute the sphere does not have, which
    // rendered every landmark black (RES-112 P-02). Joints are unlit so their
    // identity colour reads the same from every camera angle.
    const material = error
      ? new MeshBasicMaterial({ transparent: true, opacity: 0.14, depthWrite: false })
      : new MeshBasicMaterial();
    const instance = new InstancedMesh(geometry, material, count);
    instance.instanceMatrix.setUsage(DynamicDrawUsage);
    return instance;
  }, [count, error]);
  useEffect(() => () => {
    mesh.geometry.dispose();
    if (Array.isArray(mesh.material)) mesh.material.forEach((material) => material.dispose());
    else mesh.material.dispose();
  }, [mesh]);
  return mesh;
}

function BatchedSegments({ indices, currentRef, connections, color }: {
  readonly indices: readonly number[];
  readonly currentRef: React.MutableRefObject<CurrentLandmarks>;
  readonly connections: readonly DisplayConnectionDefinition[];
  readonly color: string;
}) {
  const record = useMemo(() => createLineRecord(indices.length * connections.length * 2, color), [color, connections.length, indices.length]);
  useEffect(() => () => disposeLineRecord(record), [record]);
  useFrame(() => {
    let offset = 0;
    let visible = false;
    for (const subjectIndex of indices) {
      const current = currentRef.current[subjectIndex];
      for (const connection of connections) {
        const points = connectionPoints(current?.landmarks, connection, current?.centre ?? WORLD_ORIGIN);
        if (points) visible = true;
        writeSegment(record.positions, offset, points);
        offset += 6;
      }
    }
    record.attribute.needsUpdate = true;
    record.object.visible = visible;
  });
  return <primitive object={record.object} />;
}

function BatchedAngles({ indices, currentRef, definitions, color, articulation = false }: {
  readonly indices: readonly number[];
  readonly currentRef: React.MutableRefObject<CurrentLandmarks>;
  readonly definitions: readonly AngleDefinition[];
  readonly color: string;
  readonly articulation?: boolean;
}) {
  const maxPoints = 21;
  const record = useMemo(() => createLineRecord(indices.length * definitions.length * (maxPoints - 1), color), [color, definitions.length, indices.length]);
  useEffect(() => () => disposeLineRecord(record), [record]);
  useFrame(() => {
    let offset = 0;
    let visible = false;
    for (const subjectIndex of indices) {
      const current = currentRef.current[subjectIndex];
      for (const definition of definitions) {
        const points = articulation
          ? anglePointsAt(current?.landmarks, definition, current?.centre ?? WORLD_ORIGIN, 0.075)
          : anglePath(current?.landmarks, definition, current?.centre ?? WORLD_ORIGIN);
        if (points) visible = true;
        for (let segment = 0; segment < maxPoints - 1; segment += 1) {
          writeSegment(record.positions, offset, points && points[segment] && points[segment + 1] ? [points[segment]!, points[segment + 1]!] : null);
          offset += 6;
        }
      }
    }
    record.attribute.needsUpdate = true;
    record.object.visible = visible;
  });
  return <primitive object={record.object} />;
}

interface LineRecord {
  readonly object: LineSegments;
  readonly positions: Float32Array;
  readonly attribute: BufferAttribute;
}

function createLineRecord(segmentCount: number, color: string): LineRecord {
  const positions = new Float32Array(segmentCount * 6);
  const geometry = new BufferGeometry();
  const attribute = new BufferAttribute(positions, 3);
  attribute.setUsage(DynamicDrawUsage);
  geometry.setAttribute("position", attribute);
  const object = new LineSegments(geometry, new LineBasicMaterial({ color }));
  object.visible = false;
  return { object, positions, attribute };
}

function disposeLineRecord(record: LineRecord) {
  record.object.geometry.dispose();
  if (Array.isArray(record.object.material)) record.object.material.forEach((material) => material.dispose());
  else record.object.material.dispose();
}

function writeSegment(positions: Float32Array, offset: number, points: readonly [ViewerPoint, ViewerPoint] | null) {
  if (!points) {
    positions.fill(0, offset, offset + 6);
    return;
  }
  positions.set(points[0]!, offset);
  positions.set(points[1]!, offset + 3);
}

function connectionPoints(landmarks: ReadonlyMap<string, PoseLandmark> | undefined, connection: DisplayConnectionDefinition, centre: { readonly xM: number; readonly yM: number }): readonly [ViewerPoint, ViewerPoint] | null {
  if (!landmarks) return null;
  const start = landmarks.get(connection.startLandmark);
  const end = landmarks.get(connection.endLandmark);
  return start && end ? [toViewerPoint(start, centre), toViewerPoint(end, centre)] : null;
}

function anglePath(landmarks: ReadonlyMap<string, PoseLandmark> | undefined, definition: AngleDefinition, centre: { readonly xM: number; readonly yM: number }): ViewerPoint[] | null {
  if (!landmarks) return null;
  const vertex = landmarks.get(definition.vertexLandmark);
  const first = landmarks.get(definition.firstLandmark);
  const second = landmarks.get(definition.secondLandmark);
  if (!vertex || !first || !second) return null;
  const radians = angleAt(vertex, first, second);
  return radians === null ? null : arcPoints(vertex, first, second, radians, centre);
}

function anglePointsAt(landmarks: ReadonlyMap<string, PoseLandmark> | undefined, definition: AngleDefinition, centre: { readonly xM: number; readonly yM: number }, radius: number): ViewerPoint[] | null {
  if (!landmarks) return null;
  const vertex = landmarks.get(definition.vertexLandmark);
  const first = landmarks.get(definition.firstLandmark);
  const second = landmarks.get(definition.secondLandmark);
  if (!vertex || !first || !second) return null;
  const radians = angleAt(vertex, first, second);
  return radians === null ? null : arcPoints(vertex, first, second, radians, centre, radius);
}

export function arcPoints(vertex: PoseLandmark, first: PoseLandmark, second: PoseLandmark, radians: number, centre: { readonly xM: number; readonly yM: number } = { xM: 0, yM: 0 }, radius = 0.1): ViewerPoint[] {
  const vector = (point: PoseLandmark) => {
    const x = point.xM - vertex.xM;
    const y = point.yM - vertex.yM;
    const z = point.zM - vertex.zM;
    const norm = Math.hypot(x, y, z);
    return norm === 0 ? [0, 0, 0] : [x / norm, y / norm, z / norm];
  };
  const u = vector(first);
  const v = vector(second);
  const angle = Math.min(Math.PI - 1e-6, Math.max(1e-6, radians));
  const sinAngle = Math.sin(angle);
  const points: ViewerPoint[] = [];
  for (let step = 0; step <= 20; step += 1) {
    const t = step / 20;
    const weightU = Math.sin((1 - t) * angle) / sinAngle;
    const weightV = Math.sin(t * angle) / sinAngle;
    const mixed = u.map((value, index) => value * weightU + (v[index] ?? 0) * weightV);
    const norm = Math.hypot(...mixed);
    const normalized = norm === 0 ? [0, 0, 0] : mixed.map((value) => value / norm);
    points.push(toViewerPoint({ xM: vertex.xM + normalized[0]! * radius, yM: vertex.yM + normalized[1]! * radius, zM: vertex.zM + normalized[2]! * radius }, centre));
  }
  return points;
}

export function PoseCanvas({ playing, onReady, ...scene }: PoseSceneProps & {
  readonly playing: boolean;
  readonly onReady?: () => void;
}) {
  return <Canvas frameloop={playing ? "always" : "demand"} camera={{ fov: 40, near: 0.01, far: 100 }} dpr={[1, 2]} gl={{ antialias: true }} onCreated={() => onReady?.()}>
    <PoseScene {...scene} />
  </Canvas>;
}

export default PoseCanvas;
