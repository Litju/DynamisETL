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
  MeshBasicMaterial,
  MeshStandardMaterial,
  Quaternion,
  SphereGeometry,
  Vector3,
} from "three";

import {
  angleAt,
  boundsOf,
  cameraFor,
  landmarksAt,
  planarCentre,
  toViewerPoint,
  type AngleDefinition,
  type CameraPreset,
  type DisplayConnectionDefinition,
  type PoseFrame,
  type PoseLandmark,
  type PoseSubjectFrames,
  type ProcessorOverlays,
  type ViewerPoint,
  withoutDuplicateAngles,
} from "@/components/pose/pose-model";
import { useAnalysisStore } from "@/lib/state/analysis";

export const JOINT_COLOR = "#7fd1e8";
export const SELECTED_JOINT_COLOR = "#ffd166";
export const PROVIDER_SKELETON_COLOR = "#6d9eb4";
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
const ALL_SUBJECT_COLORS = ["#7fd1e8", "#f2a65a", "#c39bea", "#8bd17c", "#f48fb1", "#ffd166"] as const;

export interface PoseSceneProps {
  readonly frames: readonly PoseFrame[];
  readonly subjectFrames: readonly PoseSubjectFrames[];
  readonly allSubjects: boolean;
  readonly overlays: ProcessorOverlays;
  readonly providerConnections: readonly DisplayConnectionDefinition[];
  readonly preset: CameraPreset;
  readonly showProviderSkeleton: boolean;
  readonly showTorsoCue: boolean;
  readonly showFootContact: boolean;
  readonly showHandContact: boolean;
  readonly showHeadNeck: boolean;
  readonly showArticulationAngles: boolean;
  readonly showSegments: boolean;
  readonly showAngles: boolean;
  readonly showErrorRadii: boolean;
}

interface LandmarkDescriptor {
  readonly subjectId: string;
  readonly subjectIndex: number;
  readonly jointName: string;
}

type CurrentLandmarks = readonly ReadonlyMap<string, PoseLandmark>[];

export function PoseScene(props: PoseSceneProps) {
  const subjects = useMemo(
    () => props.allSubjects ? props.subjectFrames : [{ subjectId: props.frames[0]?.subjectId ?? "selected", frames: props.frames }],
    [props.allSubjects, props.frames, props.subjectFrames],
  );
  const firstLandmarks = useMemo(
    () => subjects.flatMap((subject) => subject.frames.find((frame) => frame.observed)?.landmarks ?? []),
    [subjects],
  );
  const centre = useMemo(() => planarCentre(firstLandmarks), [firstLandmarks]);
  const bounds = useMemo(() => {
    const input = props.allSubjects ? subjects.flatMap((subject) => subject.frames.flatMap((frame) => frame.landmarks)) : firstLandmarks;
    return boundsOf(input, centre);
  }, [centre, firstLandmarks, props.allSubjects, subjects]);
  return <PoseStage {...props} subjects={subjects} centre={centre} bounds={bounds} />;
}

function PoseStage({ subjects, centre, bounds, ...props }: PoseSceneProps & {
  readonly subjects: readonly PoseSubjectFrames[];
  readonly centre: { readonly xM: number; readonly yM: number };
  readonly bounds: ReturnType<typeof boundsOf>;
}) {
  const { invalidate, setFrameloop } = useThree();
  const playing = useAnalysisStore((state) => state.playing);
  const controlsRef = useRef<React.ElementRef<typeof CameraControls> | null>(null);
  useEffect(() => useAnalysisStore.subscribe((state, previous) => {
    if (state.playheadNs !== previous.playheadNs || state.playing !== previous.playing) invalidate();
  }), [invalidate]);
  useEffect(() => {
    setFrameloop(playing ? "always" : "demand");
    invalidate();
  }, [invalidate, playing, setFrameloop]);
  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const { position, target } = cameraFor(props.preset, bounds);
    void controls.setLookAt(position[0], position[1], position[2], target[0], target[1], target[2], false);
    invalidate();
  }, [bounds, invalidate, props.preset]);
  return (
    <>
      <color attach="background" args={["#12161c"]} />
      <fog attach="fog" args={["#12161c", bounds.radius * 3, bounds.radius * 9]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[2, 4, 3]} intensity={1.1} />
      <Grid args={[bounds.radius * 2.6, bounds.radius * 2.6]} position={[bounds.center[0], bounds.min[1], bounds.center[2]]} cellSize={bounds.radius / 8} cellColor="#242c37" sectionSize={bounds.radius / 2} sectionColor="#33404f" fadeDistance={bounds.radius * 14} fadeStrength={1.5} />
      <CameraControls ref={controlsRef} makeDefault />
      <PoseHotPath subjects={subjects} centre={centre} {...props} />
    </>
  );
}

function PoseHotPath({ subjects, centre, overlays, providerConnections, showProviderSkeleton, showTorsoCue, showFootContact, showHandContact, showHeadNeck, showArticulationAngles, showSegments, showAngles, showErrorRadii }: PoseSceneProps & {
  readonly subjects: readonly PoseSubjectFrames[];
  readonly centre: { readonly xM: number; readonly yM: number };
}) {
  const descriptors = useMemo<LandmarkDescriptor[]>(() => subjects.flatMap((subject, subjectIndex) => {
    const names = new Set<string>();
    for (const frame of subject.frames.slice(0, 200)) for (const landmark of frame.landmarks) names.add(landmark.jointName);
    return [...names].sort().map((jointName) => ({ subjectId: subject.subjectId, subjectIndex, jointName }));
  }), [subjects]);
  const jointMesh = useInstancedGlyph(descriptors.length, false);
  const errorMesh = useInstancedGlyph(descriptors.length, true);
  const currentRef = useRef<CurrentLandmarks>([]);
  const identity = useMemo(() => new Quaternion(), []);
  const matrix = useMemo(() => new Matrix4(), []);
  const position = useMemo(() => new Vector3(), []);
  const scale = useMemo(() => new Vector3(), []);
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  const selectedEntity = useAnalysisStore((state) => state.selectedEntityId);
  const articulationAngles = useMemo(() => withoutDuplicateAngles(ARTICULATION_ANGLE_CUES, overlays.angles), [overlays.angles]);
  useFrame(() => {
    const time = useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
    const current = subjects.map((subject) => {
      const byName = new Map<string, PoseLandmark>();
      for (const landmark of landmarksAt(subject.frames, time)) byName.set(landmark.jointName, landmark);
      return byName;
    });
    currentRef.current = current;
    for (let index = 0; index < descriptors.length; index += 1) {
      const descriptor = descriptors[index]!;
      const landmark = current[descriptor.subjectIndex]?.get(descriptor.jointName);
      const visible = landmark !== undefined;
      const point = visible ? toViewerPoint(landmark, centre) : [0, 0, 0] as const;
      const selected = descriptor.jointName === selectedJoint && (selectedEntity === null || selectedEntity === descriptor.subjectId);
      position.set(point[0], point[1], point[2]);
      const jointScale = visible ? (selected ? 1.6 : 1) : 0;
      scale.set(jointScale, jointScale, jointScale);
      matrix.compose(position, identity, scale);
      jointMesh.setMatrixAt(index, matrix);
      jointMesh.setColorAt(index, new Color(selected ? SELECTED_JOINT_COLOR : subjectColor(descriptor.subjectIndex, subjects.length)));
      const errorScale = showErrorRadii && visible && landmark.errorM !== null && landmark.errorM > 0 ? landmark.errorM : 0;
      scale.set(errorScale, errorScale, errorScale);
      matrix.compose(position, identity, scale);
      errorMesh.setMatrixAt(index, matrix);
      errorMesh.setColorAt(index, new Color(ERROR_RADIUS_COLOR));
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
    const state = useAnalysisStore.getState();
    state.selectJoint(descriptor.jointName);
    if (subjects.length > 1) state.selectEntity(descriptor.subjectId);
  }, [descriptors, subjects.length]);
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
      {showProviderSkeleton ? <BatchedSegments subjects={subjects} currentRef={currentRef} centre={centre} connections={providerConnections} color={PROVIDER_SKELETON_COLOR} /> : null}
      {showTorsoCue ? <BatchedSegments subjects={subjects} currentRef={currentRef} centre={centre} connections={TORSO_CUE_CONNECTIONS} color={TORSO_CUE_COLOR} /> : null}
      {showFootContact ? <BatchedSegments subjects={subjects} currentRef={currentRef} centre={centre} connections={FOOT_CONTACT_CUE_CONNECTIONS} color={FOOT_CONTACT_CUE_COLOR} /> : null}
      {showHandContact ? <BatchedSegments subjects={subjects} currentRef={currentRef} centre={centre} connections={HAND_CONTACT_CUE_CONNECTIONS} color={FOOT_CONTACT_CUE_COLOR} /> : null}
      {showHeadNeck ? <BatchedSegments subjects={subjects} currentRef={currentRef} centre={centre} connections={HEAD_NECK_CUE_CONNECTIONS} color={HEAD_NECK_CUE_COLOR} /> : null}
      {processorSegments.length > 0 ? <BatchedSegments subjects={subjects} currentRef={currentRef} centre={centre} connections={processorSegments} color={SEGMENT_COLOR} /> : null}
      {showAngles && overlays.angles.length > 0 ? <BatchedAngles subjects={subjects} currentRef={currentRef} centre={centre} definitions={overlays.angles} color={ANGLE_COLOR} /> : null}
      {showArticulationAngles && articulationAngles.length > 0 ? <BatchedAngles subjects={subjects} currentRef={currentRef} centre={centre} definitions={articulationAngles} color={ARTICULATION_ANGLE_CUE_COLOR} articulation /> : null}
    </>
  );
}

function useInstancedGlyph(count: number, error: boolean): InstancedMesh {
  const mesh = useMemo(() => {
    const geometry = new SphereGeometry(error ? 1 : 0.026, error ? 8 : 12, error ? 8 : 12);
    const material = error ? new MeshBasicMaterial({ transparent: true, opacity: 0.12, depthWrite: false, vertexColors: true }) : new MeshStandardMaterial({ vertexColors: true, roughness: 0.35, metalness: 0.05 });
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

function subjectColor(index: number, count: number): string {
  return count <= 1 ? JOINT_COLOR : ALL_SUBJECT_COLORS[index % ALL_SUBJECT_COLORS.length]!;
}

function BatchedSegments({ subjects, currentRef, centre, connections, color }: {
  readonly subjects: readonly PoseSubjectFrames[];
  readonly currentRef: React.MutableRefObject<CurrentLandmarks>;
  readonly centre: { readonly xM: number; readonly yM: number };
  readonly connections: readonly DisplayConnectionDefinition[];
  readonly color: string;
}) {
  const record = useMemo(() => createLineRecord(subjects.length * connections.length * 2, color), [color, connections.length, subjects.length]);
  useEffect(() => () => disposeLineRecord(record), [record]);
  useFrame(() => {
    let offset = 0;
    let visible = false;
    for (let subjectIndex = 0; subjectIndex < subjects.length; subjectIndex += 1) {
      const landmarks = currentRef.current[subjectIndex];
      for (const connection of connections) {
        const points = connectionPoints(landmarks, connection, centre);
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

function BatchedAngles({ subjects, currentRef, centre, definitions, color, articulation = false }: {
  readonly subjects: readonly PoseSubjectFrames[];
  readonly currentRef: React.MutableRefObject<CurrentLandmarks>;
  readonly centre: { readonly xM: number; readonly yM: number };
  readonly definitions: readonly AngleDefinition[];
  readonly color: string;
  readonly articulation?: boolean;
}) {
  const maxPoints = 21;
  const record = useMemo(() => createLineRecord(subjects.length * definitions.length * (maxPoints - 1), color), [color, definitions.length, subjects.length]);
  useEffect(() => () => disposeLineRecord(record), [record]);
  useFrame(() => {
    let offset = 0;
    let visible = false;
    for (let subjectIndex = 0; subjectIndex < subjects.length; subjectIndex += 1) {
      const landmarks = currentRef.current[subjectIndex];
      for (const definition of definitions) {
        const points = articulation ? anglePointsAt(landmarks, definition, centre, 0.075) : anglePath(landmarks, definition, centre);
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

export function PoseCanvas({ frames, subjectFrames, allSubjects, overlays, providerConnections, preset, playing, showProviderSkeleton, showTorsoCue, showFootContact, showHandContact, showHeadNeck, showArticulationAngles, showSegments, showAngles, showErrorRadii, onReady }: {
  readonly frames: readonly PoseFrame[];
  readonly subjectFrames: readonly PoseSubjectFrames[];
  readonly allSubjects: boolean;
  readonly overlays: ProcessorOverlays;
  readonly providerConnections: readonly DisplayConnectionDefinition[];
  readonly preset: CameraPreset;
  readonly playing: boolean;
  readonly showProviderSkeleton: boolean;
  readonly showTorsoCue: boolean;
  readonly showFootContact: boolean;
  readonly showHandContact: boolean;
  readonly showHeadNeck: boolean;
  readonly showArticulationAngles: boolean;
  readonly showSegments: boolean;
  readonly showAngles: boolean;
  readonly showErrorRadii: boolean;
  readonly onReady?: () => void;
}) {
  return <Canvas frameloop={playing ? "always" : "demand"} camera={{ fov: 40, near: 0.01, far: 100 }} dpr={[1, 2]} gl={{ antialias: true }} onCreated={() => onReady?.()}>
    <PoseScene frames={frames} subjectFrames={subjectFrames} allSubjects={allSubjects} overlays={overlays} providerConnections={providerConnections} preset={preset} showProviderSkeleton={showProviderSkeleton} showTorsoCue={showTorsoCue} showFootContact={showFootContact} showHandContact={showHandContact} showHeadNeck={showHeadNeck} showArticulationAngles={showArticulationAngles} showSegments={showSegments} showAngles={showAngles} showErrorRadii={showErrorRadii} />
  </Canvas>;
}

export default PoseCanvas;
