import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  CircleGeometry,
  Color,
  DoubleSide,
  InstancedMesh,
  Matrix4,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  RingGeometry,
  SphereGeometry,
} from "three";

import { TRACKING_KIND, trackingFrameIndexAt, type TrackingWindowBuffers } from "@/components/matchlab/frame-buffers";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import { FIELD_RENDER_DEPTH_M } from "@/components/matchlab/render-layer-depths";

const MARKER_Y = FIELD_RENDER_DEPTH_M.trackingMarker;

export interface TrackingLayerPalette {
  readonly home: string;
  readonly away: string;
  readonly other: string;
  readonly ball: string;
}

function kindName(kind: number): string {
  if (kind === TRACKING_KIND.player) return "player";
  if (kind === TRACKING_KIND.goalkeeper) return "goalkeeper";
  if (kind === TRACKING_KIND.ball) return "ball";
  if (kind === TRACKING_KIND.official) return "official";
  return "other";
}

function markerMesh(geometry: CircleGeometry | RingGeometry, capacity: number): InstancedMesh {
  return new InstancedMesh(
    geometry,
    new MeshBasicMaterial({ color: "#ffffff", vertexColors: true, side: DoubleSide }),
    capacity,
  );
}

export function TrackingLayer({
  frameBuffers,
  matchFrame,
  teamOrder,
  palette,
  maxAgeNs,
  sourceId,
  visible = true,
}: {
  readonly frameBuffers: TrackingWindowBuffers | null;
  readonly matchFrame: MatchFrameContextValue;
  readonly teamOrder: readonly string[];
  readonly palette: TrackingLayerPalette;
  readonly maxAgeNs: number;
  readonly sourceId: string;
  readonly visible?: boolean;
}) {
  const capacity = useMemo(() => {
    if (frameBuffers === null) return 1;
    let maximum = 1;
    for (let frame = 0; frame < frameBuffers.frameTimesNs.length; frame += 1) {
      maximum = Math.max(maximum, frameBuffers.frameOffsets[frame + 1]! - frameBuffers.frameOffsets[frame]!);
    }
    return maximum;
  }, [frameBuffers]);
  const detectedMesh = useMemo(
    () => markerMesh(new CircleGeometry(0.34, 16), capacity),
    [capacity],
  );
  const extrapolatedMesh = useMemo(
    () => markerMesh(new RingGeometry(0.22, 0.34, 16), capacity),
    [capacity],
  );
  const unknownMesh = useMemo(
    () => markerMesh(new RingGeometry(0.2, 0.32, 16), capacity),
    [capacity],
  );
  const detectedRef = useRef<InstancedMesh | null>(null);
  const extrapolatedRef = useRef<InstancedMesh | null>(null);
  const unknownRef = useRef<InstancedMesh | null>(null);
  const ballGeometry = useMemo(() => new SphereGeometry(0.16, 12, 10), []);
  const ballMaterial = useMemo(() => new MeshStandardMaterial({ color: palette.ball }), [palette.ball]);
  const ballRef = useRef<Object3D | null>(null);
  const detectedRows = useRef<number[]>([]);
  const extrapolatedRows = useRef<number[]>([]);
  const unknownRows = useRef<number[]>([]);
  const ballId = useRef<string | null>(null);
  const matrix = useMemo(() => new Matrix4(), []);
  const marker = useMemo(() => new Object3D(), []);
  const color = useMemo(() => new Color(), []);
  const lastDrawKey = useRef("unknown");

  useEffect(
    () => () => {
      for (const mesh of [detectedMesh, extrapolatedMesh, unknownMesh]) {
        mesh.geometry.dispose();
        (mesh.material as MeshBasicMaterial | MeshStandardMaterial).dispose();
      }
      ballGeometry.dispose();
      ballMaterial.dispose();
    },
    [ballGeometry, ballMaterial, detectedMesh, extrapolatedMesh, unknownMesh],
  );

  useFrame(() => {
    const buffers = frameBuffers;
    const detected = detectedRef.current;
    const extrapolated = extrapolatedRef.current;
    const unknown = unknownRef.current;
    if (detected === null || extrapolated === null || unknown === null) return;
    const timeNs = matchFrame.getCurrentTimeNs();
    const frameIndex =
      buffers === null ? -1 : trackingFrameIndexAt(buffers.frameTimesNs, timeNs, maxAgeNs);
    const sourceTimeNs = frameIndex >= 0 && buffers !== null ? buffers.frameTimesNs[frameIndex]! : null;
    const frameKey =
      sourceTimeNs === null
        ? sourceId + ":absent:" + String(visible)
        : sourceId + ":" + sourceTimeNs + ":" + String(visible) + ":" +
          (matchFrame.selectedTrackingObjectId ?? "") + ":" + (matchFrame.hoveredPlayerId ?? "") +
          ":" + palette.home + ":" + palette.away;
    if (frameKey === lastDrawKey.current) return;
    lastDrawKey.current = frameKey;

    if (sourceTimeNs === null || buffers === null) {
      detected.count = 0;
      extrapolated.count = 0;
      unknown.count = 0;
      if (ballRef.current) ballRef.current.visible = false;
      matchFrame.reportResolvedFrame("tracking", {
        identity: null,
        canonicalTimeNs: null,
        availability: "absent",
      });
      return;
    }

    matchFrame.reportResolvedFrame("tracking", {
      identity: sourceId + ":" + sourceTimeNs,
      canonicalTimeNs: sourceTimeNs,
      availability: "available",
    });
    if (!visible) {
      detected.count = 0;
      extrapolated.count = 0;
      unknown.count = 0;
      if (ballRef.current) ballRef.current.visible = false;
      return;
    }

    let detectedCount = 0;
    let extrapolatedCount = 0;
    let unknownCount = 0;
    const start = buffers.frameOffsets[frameIndex]!;
    const end = buffers.frameOffsets[frameIndex + 1]!;
    const selectedId = matchFrame.selectedTrackingObjectId;
    const hoveredId = matchFrame.hoveredPlayerId;

    for (let row = start; row < end; row += 1) {
      const entityId = buffers.entityIds[buffers.entityIndexes[row]!] ?? "";
      const kind = buffers.objectKinds[row] ?? TRACKING_KIND.other;
      const xM = buffers.positionsXY[row * 2] ?? 0;
      const yM = buffers.positionsXY[row * 2 + 1] ?? 0;
      if (kind === TRACKING_KIND.ball) {
        ballId.current = entityId;
        if (ballRef.current) {
          ballRef.current.visible = true;
          ballRef.current.position.set(xM, FIELD_RENDER_DEPTH_M.ballCenter, -yM);
          const selected = selectedId === entityId || hoveredId === entityId;
          ballRef.current.scale.setScalar(selected ? 1.35 : 1);
        }
        continue;
      }

      const teamIndex = buffers.teamIndexes[row] ?? -1;
      const teamId = teamIndex < 0 ? null : (buffers.teamIds[teamIndex] ?? null);
      const teamColor =
        teamId !== null && teamId === teamOrder[0]
          ? palette.home
          : teamId !== null && teamId === teamOrder[1]
            ? palette.away
            : palette.other;
      const selected = selectedId === entityId;
      const hovered = hoveredId === entityId;
      const scale = selected ? 1.55 : hovered ? 1.35 : kind === TRACKING_KIND.official ? 0.9 : 1;
      const detection = buffers.detectionState[row] ?? -1;
      const mesh =
        detection === 1 ? detected : detection === 0 ? extrapolated : unknown;
      const markerRows =
        detection === 1 ? detectedRows.current : detection === 0 ? extrapolatedRows.current : unknownRows.current;
      const instance =
        detection === 1 ? detectedCount++ : detection === 0 ? extrapolatedCount++ : unknownCount++;
      markerRows[instance] = row;
      marker.position.set(xM, MARKER_Y, -yM);
      marker.rotation.set(-Math.PI / 2, 0, 0);
      marker.scale.setScalar(scale);
      marker.updateMatrix();
      matrix.copy(marker.matrix);
      mesh.setMatrixAt(instance, matrix);
      color.set(selected || hovered ? "#f4f7f6" : teamColor);
      mesh.setColorAt(instance, color);
    }

    detected.count = detectedCount;
    extrapolated.count = extrapolatedCount;
    unknown.count = unknownCount;
    for (const mesh of [detected, extrapolated, unknown]) {
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
  });

  const entityAtInstance = (instanceId: number | undefined, rows: readonly number[]) => {
    if (instanceId === undefined || frameBuffers === null) return null;
    const row = rows[instanceId];
    if (row === undefined) return null;
    const entityId = frameBuffers.entityIds[frameBuffers.entityIndexes[row]!];
    return entityId ? { entityId, kind: kindName(frameBuffers.objectKinds[row] ?? TRACKING_KIND.other) } : null;
  };
  const onSelectInstance = (event: { stopPropagation: () => void; instanceId?: number }, rows: readonly number[]) => {
    event.stopPropagation();
    const selected = entityAtInstance(event.instanceId, rows);
    if (selected) matchFrame.selectTrackingObject(selected.entityId, selected.kind);
  };

  const hoverInstance = (event: { instanceId?: number }, rows: readonly number[]) => {
    const hovered = entityAtInstance(event.instanceId, rows);
    matchFrame.hoverTrackingObject(hovered?.entityId ?? null);
  };

  return (
    <group name="TrackingLayer" visible={visible}>
      <primitive
        object={detectedMesh}
        ref={detectedRef}
        dispose={null}
        onClick={(event: { stopPropagation: () => void; instanceId?: number }) => onSelectInstance(event, detectedRows.current)}
        onPointerOver={(event: { instanceId?: number }) => hoverInstance(event, detectedRows.current)}
        onPointerOut={() => matchFrame.hoverTrackingObject(null)}
      />
      <primitive
        object={extrapolatedMesh}
        ref={extrapolatedRef}
        dispose={null}
        onClick={(event: { stopPropagation: () => void; instanceId?: number }) => onSelectInstance(event, extrapolatedRows.current)}
        onPointerOver={(event: { instanceId?: number }) => hoverInstance(event, extrapolatedRows.current)}
        onPointerOut={() => matchFrame.hoverTrackingObject(null)}
      />
      <primitive
        object={unknownMesh}
        ref={unknownRef}
        dispose={null}
        onClick={(event: { stopPropagation: () => void; instanceId?: number }) => onSelectInstance(event, unknownRows.current)}
        onPointerOver={(event: { instanceId?: number }) => hoverInstance(event, unknownRows.current)}
        onPointerOut={() => matchFrame.hoverTrackingObject(null)}
      />
      <mesh
        ref={ballRef}
        geometry={ballGeometry}
        material={ballMaterial}
        onClick={(event) => {
          event.stopPropagation();
          if (ballId.current !== null) matchFrame.selectTrackingObject(ballId.current, "ball");
        }}
        onPointerOver={() => matchFrame.hoverTrackingObject(ballId.current)}
        onPointerOut={() => matchFrame.hoverTrackingObject(null)}
      />
    </group>
  );
}
