import { CameraControls, Html, View } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, forwardRef } from "react";

import { MatchWorld } from "@/components/matchlab/MatchWorld";
import {
  TRACKING_KIND,
  tacticalOverlayAtBuffers,
  trackingEntityAt,
  trackingFrameIndexAt,
  trailPointsForTrackingBuffer,
  type TacticalGridWindowBuffers,
  type TacticalPolygonWindowBuffers,
  type TrackingWindowBuffers,
} from "@/components/matchlab/frame-buffers";
import type { ContextSubject } from "@/components/matchlab/ContextLayer";
import type { PitchEvent, PitchLayers } from "@/components/matchlab/render-types";
import type { EntityFrame } from "@/components/pitch/pitch-model";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import type { TrackingLayerPalette } from "@/components/matchlab/TrackingLayer";
import type { TacticalLayerPalette } from "@/components/matchlab/TacticalLayer";
import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";

export interface FieldSceneViewHandle {
  resetView(): void;
}

interface FieldCameraHandle {
  resetView(): void;
}

interface FieldSceneViewProps {
  readonly matchFrame: MatchFrameContextValue;
  readonly trackingBuffers: TrackingWindowBuffers;
  readonly geometryBuffers: TacticalPolygonWindowBuffers;
  readonly territoryBuffers: TacticalPolygonWindowBuffers;
  readonly influenceBuffers: TacticalGridWindowBuffers;
  readonly trackingMaxAgeNs: number;
  readonly influenceMaxAgeNs: number;
  readonly teamOrder: readonly string[];
  readonly teamLabels: ReadonlyMap<string, string>;
  readonly entityLabels: ReadonlyMap<string, string>;
  readonly trackingPalette: TrackingLayerPalette;
  readonly tacticalPalette: TacticalLayerPalette;
  readonly events: readonly PitchEvent[];
  readonly layers: PitchLayers;
  readonly onReady: () => void;
  readonly onInfluenceGridTime: (timeNs: bigint | null) => void;
}

export const FieldSceneView = forwardRef<FieldSceneViewHandle, FieldSceneViewProps>(function FieldSceneView({
  matchFrame,
  trackingBuffers,
  geometryBuffers,
  territoryBuffers,
  influenceBuffers,
  trackingMaxAgeNs,
  influenceMaxAgeNs,
  teamOrder,
  teamLabels,
  entityLabels,
  trackingPalette,
  tacticalPalette,
  events,
  layers,
  onReady,
  onInfluenceGridTime,
}, ref) {
  const cameraRef = useRef<FieldCameraHandle | null>(null);
  const committedRange = useAnalysisStore((state) => state.committedRangeNs);
  const frameIndex = useAnalysisStore(useCallback(
    (state) => trackingFrameIndexAt(
      trackingBuffers.frameTimesNs,
      effectiveTimeNs(state),
      trackingMaxAgeNs,
    ),
    [trackingBuffers, trackingMaxAgeNs],
  ));
  const frameTimeNs = frameIndex < 0 ? null : trackingBuffers.frameTimesNs[frameIndex] ?? null;
  const trackingEntity = trackingEntityAt(trackingBuffers, frameIndex, matchFrame.selectedTrackingObjectId);
  const hoveredEntity = trackingEntityAt(trackingBuffers, frameIndex, matchFrame.hoveredPlayerId);
  const selected = useMemo(
    () => contextSubject(trackingEntity, teamLabels, entityLabels),
    [entityLabels, teamLabels, trackingEntity],
  );
  const hovered = useMemo(
    () => contextSubject(hoveredEntity, teamLabels, entityLabels),
    [entityLabels, teamLabels, hoveredEntity],
  );
  const trail = useMemo(
    () => layers.trails
      ? trailPointsForTrackingBuffer(trackingBuffers, committedRange, matchFrame.selectedTrackingObjectId)
      : [],
    [committedRange, layers.trails, matchFrame.selectedTrackingObjectId, trackingBuffers],
  );
  const roleOf = useCallback(
    (groupId: string) => groupId === teamOrder[0] ? "home" : groupId === teamOrder[1] ? "away" : "other",
    [teamOrder],
  );
  const tacticalOverlay = useMemo(
    () => tacticalOverlayAtBuffers(
      { geometry: geometryBuffers, territory: territoryBuffers, influence: influenceBuffers },
      frameTimeNs,
      roleOf,
      influenceMaxAgeNs,
    ),
    [frameTimeNs, geometryBuffers, influenceBuffers, influenceMaxAgeNs, roleOf, territoryBuffers],
  );
  useEffect(
    () => onInfluenceGridTime(tacticalOverlay.influenceGridTimeNs),
    [onInfluenceGridTime, tacticalOverlay.influenceGridTimeNs],
  );

  const dimensions = matchFrame.trackingSource?.pitchDimensionsM ?? null;
  const cameraDistance = dimensions === null
    ? 80
    : Math.max(dimensions.lengthM, dimensions.widthM) * 1.2;
  useImperativeHandle(ref, () => ({ resetView: () => cameraRef.current?.resetView() }), []);
  return (
    <View className="absolute inset-0" style={{ width: "100%", height: "100%" }} index={2}>
      <color attach="background" args={["#111820"]} />
      <ambientLight intensity={1.25} />
      <directionalLight position={[0, cameraDistance, 0]} intensity={1.1} />
      <FieldCamera ref={cameraRef} cameraDistance={cameraDistance} />
      <MatchWorld
        matchFrame={matchFrame}
        visibility={{
          pitch: true,
          tracking: true,
          tactical: layers.geometry || layers.territory || layers.influence || layers.events,
          pose: false,
          context: layers.trails || selected !== null || hovered !== null,
        }}
        trackingBuffers={trackingBuffers}
        trackingMaxAgeNs={trackingMaxAgeNs}
        teamOrder={teamOrder}
        trackingPalette={trackingPalette}
        tacticalOverlay={tacticalOverlay.overlay}
        tacticalLayers={layers}
        events={events}
        tacticalPalette={tacticalPalette}
        poseLayer={null}
        context={{ selected, hovered, trail }}
      />
      {layers.labels ? (
        <FieldEntityLabels
          buffers={trackingBuffers}
          frameIndex={frameIndex}
          labels={entityLabels}
          selectedId={matchFrame.selectedTrackingObjectId}
        />
      ) : null}
      <SceneReady onReady={onReady} />
    </View>
  );
});

function contextSubject(
  entity: EntityFrame | null,
  teamLabels: ReadonlyMap<string, string>,
  entityLabels: ReadonlyMap<string, string>,
): ContextSubject | null {
  if (entity === null || entity.isBall) return null;
  return {
    id: entity.objectId,
    label: entityLabels.get(entity.objectId) ??
      (entity.groupId === null ? "Unassigned" : teamLabels.get(entity.groupId) ?? entity.groupId),
    xM: entity.xM,
    yM: entity.yM,
  };
}

function FieldEntityLabels({
  buffers,
  frameIndex,
  labels,
  selectedId,
}: {
  readonly buffers: TrackingWindowBuffers;
  readonly frameIndex: number;
  readonly labels: ReadonlyMap<string, string>;
  readonly selectedId: string | null;
}) {
  if (frameIndex < 0) return null;
  const start = buffers.frameOffsets[frameIndex]!;
  const end = buffers.frameOffsets[frameIndex + 1]!;
  const items = [];
  for (let row = start; row < end; row += 1) {
    const entityIndex = buffers.entityIndexes[row]!;
    const entityId = buffers.entityIds[entityIndex] ?? "";
    if (!entityId || (buffers.objectKinds[row] ?? TRACKING_KIND.other) === TRACKING_KIND.ball) continue;
    items.push({
      id: entityId,
      xM: buffers.positionsXY[row * 2]!,
      yM: buffers.positionsXY[row * 2 + 1]!,
      selected: entityId === selectedId,
      text: labels.get(entityId) ?? (entityId.length > 8 ? entityId.slice(-5) : entityId),
    });
  }
  return items.map((item) => (
    <Html key={item.id} position={[item.xM, 0.38, -item.yM]} center distanceFactor={90}>
      <span className={item.selected
        ? "pointer-events-none rounded bg-black/85 px-1 py-0.5 text-[10px] font-semibold text-white"
        : "pointer-events-none rounded bg-black/65 px-1 py-0.5 text-[9px] text-white/85"}>
        {item.text}
      </span>
    </Html>
  ));
}

function SceneReady({ onReady }: { readonly onReady: () => void }) {
  useEffect(() => onReady(), [onReady]);
  return null;
}

const FieldCamera = forwardRef<FieldCameraHandle, { readonly cameraDistance: number }>(function FieldCamera({
  cameraDistance,
}, ref) {
  const camera = useThree((state) => state.camera);
  const invalidate = useThree((state) => state.invalidate);
  const controlsRef = useRef<React.ElementRef<typeof CameraControls> | null>(null);
  const resetView = useCallback(() => {
    camera.up.set(0, 0, -1);
    camera.position.set(0, cameraDistance, 0);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    void controlsRef.current?.setLookAt(0, cameraDistance, 0, 0, 0, 0, false);
    invalidate();
  }, [camera, cameraDistance, invalidate]);
  useImperativeHandle(ref, () => ({ resetView }), [resetView]);
  useEffect(() => {
    /* eslint-disable react-hooks/immutability -- camera pose is mutable renderer state in R3F. */
    camera.up.set(0, 0, -1);
    if ("isPerspectiveCamera" in camera) {
      camera.near = 0.1;
      camera.fov = 38;
      camera.far = cameraDistance * 5;
      camera.updateProjectionMatrix();
    }
    resetView();
    return () => {
      camera.up.set(0, 1, 0);
      camera.position.set(0, 0, 5);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();
    };
    /* eslint-enable react-hooks/immutability */
  }, [camera, cameraDistance, resetView]);
  return (
    <CameraControls
      ref={controlsRef}
      camera={camera}
      makeDefault
      minDistance={cameraDistance * 0.35}
      maxDistance={cameraDistance * 3}
    />
  );
});
