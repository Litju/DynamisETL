import { CameraControls, OrthographicCamera, PerspectiveCamera, View } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from "react";
import { OrthographicCamera as ThreeOrthographicCamera, PCFShadowMap, PerspectiveCamera as ThreePerspectiveCamera } from "three";
import { Vector3 } from "three";
import type { Camera as ThreeCamera, OrthographicCamera as OrthographicCameraType, PerspectiveCamera as PerspectiveCameraType } from "three";

import { MatchWorld } from "@/components/matchlab/MatchWorld";
import { FIELD_RENDER_DEPTH_M } from "@/components/matchlab/render-layer-depths";
import { ARRIVAL_TIME_FIELD_SPEC, ARRIVAL_TIME_ELEVATION_SPEC, describeElevationSpec } from "@/components/matchlab/elevation-specs";
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
import type { TacticalRow } from "@/components/pitch/tactical-overlay";
import type { EntityFrame } from "@/components/pitch/pitch-model";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import type { TrackingLayerPalette } from "@/components/matchlab/TrackingLayer";
import type { TacticalLayerPalette } from "@/components/matchlab/TacticalLayer";
import { EMPTY_TACTICAL_V3_INDEX, jsonIds, tacticalV3FrameAt, unitPointInSourceFrame, type TacticalV3Index } from "@/components/pitch/tactical-v3";
import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";
import type { ScalarFieldMode, TacticalRelationMode } from "@/lib/state/analysis";

export type FieldCameraMode = "tactical-map" | "structure-lift" | "perspective";

export interface FieldSceneViewHandle {
  resetView(): void;
  setCameraMode(mode: FieldCameraMode): void;
  focusSelected(): void;
}

interface FieldCameraHandle {
  resetView(): void;
  setCameraMode(mode: FieldCameraMode): void;
  focusAt(xM: number, yM: number): void;
  getCamera(): ThreeCamera | null;
}

interface FieldSceneViewProps {
  readonly hostRef: React.RefObject<HTMLDivElement | null>;
  readonly matchFrame: MatchFrameContextValue;
  readonly trackingBuffers: TrackingWindowBuffers;
  readonly geometryBuffers: TacticalPolygonWindowBuffers;
  readonly territoryBuffers: TacticalPolygonWindowBuffers;
  readonly influenceBuffers: TacticalGridWindowBuffers;
  readonly tacticalV3Index?: TacticalV3Index;
  readonly tacticalRelationMode?: TacticalRelationMode;
  readonly scalarFieldMode?: ScalarFieldMode;
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
  readonly cameraMode: FieldCameraMode;
  readonly onCameraModeChange: (mode: FieldCameraMode) => void;
}

export const FieldSceneView = forwardRef<FieldSceneViewHandle, FieldSceneViewProps>(function FieldSceneView({
  hostRef,
  matchFrame,
  trackingBuffers,
  geometryBuffers,
  territoryBuffers,
  influenceBuffers,
  tacticalV3Index = EMPTY_TACTICAL_V3_INDEX,
  tacticalRelationMode = "off",
  scalarFieldMode = "heatmap",
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
  cameraMode,
  onCameraModeChange,
}, ref) {
  const cameraRef = useRef<FieldCameraHandle | null>(null);
  const shadowBenchmarkOff = import.meta.env.DEV && typeof window !== "undefined" &&
    window.localStorage.getItem("dynamis-matchlab-field-shadow-benchmark") === "off";
  const shadowEnabled = cameraMode === "structure-lift" && !shadowBenchmarkOff;
  const reportElevationUpdate = useCallback((state: { readonly valid: boolean; readonly vertexCount: number; readonly gridTimeNs: bigint | null }) => {
    const host = hostRef.current;
    if (!host) return;
    host.dataset.scalarSurfaceReady = String(state.valid);
    host.dataset.scalarSurfaceVertices = String(state.vertexCount);
    host.dataset.scalarSurfaceGridTimeNs = state.gridTimeNs?.toString() ?? "";
  }, [hostRef]);
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
  const tacticalV3Frame = tacticalV3FrameAt(tacticalV3Index, frameTimeNs);
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
      false,
    ),
    [frameTimeNs, geometryBuffers, influenceBuffers, influenceMaxAgeNs, roleOf, territoryBuffers],
  );
  const scalarGridIndex = layers.influence && frameTimeNs !== null
    ? trackingFrameIndexAt(influenceBuffers.gridTimesNs, frameTimeNs, influenceMaxAgeNs)
    : -1;
  const scalarGridCellCount = scalarGridIndex < 0
    ? 0
    : influenceBuffers.gridOffsets[scalarGridIndex + 1]! - influenceBuffers.gridOffsets[scalarGridIndex]!;
  useEffect(
    () => onInfluenceGridTime(tacticalOverlay.influenceGridTimeNs),
    [onInfluenceGridTime, tacticalOverlay.influenceGridTimeNs],
  );

  const dimensions = matchFrame.trackingSource?.pitchDimensionsM ?? null;
  const cameraDistance = dimensions === null
    ? 80
    : Math.max(dimensions.lengthM, dimensions.widthM) * 1.2;
  useImperativeHandle(ref, () => ({
    resetView: () => cameraRef.current?.resetView(),
    setCameraMode: (mode) => cameraRef.current?.setCameraMode(mode),
    focusSelected: () => {
      if (trackingEntity && !trackingEntity.isBall) cameraRef.current?.focusAt(trackingEntity.xM, -trackingEntity.yM);
    },
  }), [trackingEntity]);
  return (
    <>
    <View className="absolute inset-0" style={{ width: "100%", height: "100%" }} index={2}>
      <color attach="background" args={["#111820"]} />
      <ambientLight intensity={shadowEnabled ? 0.45 : 0.78} />
      {shadowEnabled ? (
        <directionalLight
          position={[-(dimensions?.lengthM ?? cameraDistance) * 0.6, cameraDistance * 0.3, (dimensions?.widthM ?? cameraDistance / 1.5) * 1.2]}
          intensity={1.15}
          castShadow
          shadow-mapSize={[1024, 1024]}
          shadow-camera-left={-(dimensions?.lengthM ?? cameraDistance) * 0.62}
          shadow-camera-right={(dimensions?.lengthM ?? cameraDistance) * 0.62}
          shadow-camera-top={(dimensions?.widthM ?? cameraDistance / 1.5) * 1.4}
          shadow-camera-bottom={-(dimensions?.widthM ?? cameraDistance / 1.5) * 1.4}
          shadow-bias={-0.00015}
          shadow-normalBias={0.012}
          shadow-radius={3}
        />
      ) : null}
      <FieldCamera ref={cameraRef} mode={cameraMode} onModeChange={onCameraModeChange} cameraDistance={cameraDistance} dimensions={dimensions} hostRef={hostRef} />
      <FieldViewRender cameraRef={cameraRef} hostRef={hostRef} shadowEnabled={shadowEnabled} shadowUpdateKey={tacticalOverlay.influenceGridTimeNs?.toString() ?? "none"} />
      <MatchWorld
        matchFrame={matchFrame}
        visibility={{
          pitch: true,
          tracking: true,
          tactical: layers.geometry || layers.territory || layers.influence || layers.events || tacticalV3Frame.units.length > 0,
          pose: false,
          context: layers.trails || selected !== null || hovered !== null,
        }}
        trackingBuffers={trackingBuffers}
        trackingMaxAgeNs={trackingMaxAgeNs}
        teamOrder={teamOrder}
        trackingPalette={trackingPalette}
        tacticalOverlay={tacticalOverlay.overlay}
        tacticalV3={tacticalV3Frame}
        tacticalRelationMode={tacticalRelationMode}
        trackingFrameIndex={frameIndex}
        tacticalLayers={layers}
        scalarField={{
          buffers: influenceBuffers,
          spec: { ...ARRIVAL_TIME_FIELD_SPEC, mode: scalarFieldMode },
          maxAgeNs: influenceMaxAgeNs,
          visible: layers.influence,
          castShadow: shadowEnabled && scalarFieldMode === "elevation",
          onElevationUpdate: reportElevationUpdate,
        }}
        events={events}
        tacticalPalette={tacticalPalette}
        poseLayer={null}
        context={{ selected, hovered, trail }}
      />
      <FieldFrameEvidence
        hostRef={hostRef}
        cameraRef={cameraRef}
        sourceFrameNs={frameTimeNs}
        sourceId={matchFrame.trackingSource?.artifactId ?? matchFrame.trackingSource?.streamId ?? "tracking"}
        selectedPlayerId={matchFrame.selectedPlayerId}
        hullCount={tacticalOverlay.overlay.hulls.length}
        territoryCellCount={tacticalOverlay.overlay.territoryCells.length}
        influenceCellCount={scalarGridCellCount}
        v3UnitCount={tacticalV3Frame.units.length}
        v3StableEdgeCount={tacticalV3Frame.edges.filter((row) => row["stable_edge"] === true).length}
        v3StableTriangleCount={tacticalV3Frame.triangles.filter((row) => row["stable_triangle"] === true).length}
        v3InteractionCount={tacticalV3Frame.interactions.length}
        relationMode={tacticalRelationMode}
        cameraMode={cameraMode}
        shadowEnabled={shadowEnabled}
      />
      <SceneReady onReady={onReady} />
    </View>
    {layers.labels ? (
      <FieldEntityLabels
        hostRef={hostRef}
        cameraRef={cameraRef}
        buffers={trackingBuffers}
        frameIndex={frameIndex}
        labels={entityLabels}
        selectedId={matchFrame.selectedTrackingObjectId}
        matchFrame={matchFrame}
      />
    ) : null}
    {tacticalV3Frame.units.length > 0 ? (
      <FieldFunctionalUnitLabels
        hostRef={hostRef}
        cameraRef={cameraRef}
        units={tacticalV3Frame.units}
        teamOrder={teamOrder}
        teamLabels={teamLabels}
        homeColor={tacticalPalette.home}
        awayColor={tacticalPalette.away}
        selectedPlayerId={matchFrame.selectedTrackingObjectId}
      />
    ) : null}
    {layers.influence && scalarFieldMode === "elevation" && scalarGridCellCount > 0 ? (
      <div
        data-testid="analytical-elevation-disclaimer"
        role="note"
        className="pointer-events-none absolute right-3 top-3 z-20 rounded bg-black/80 px-2 py-1 text-[10px] font-medium tracking-wide text-white shadow"
        aria-label={describeElevationSpec(ARRIVAL_TIME_ELEVATION_SPEC)}
        title={describeElevationSpec(ARRIVAL_TIME_ELEVATION_SPEC)}
      >
        ANALYTICAL ELEVATION · NOT PHYSICAL HEIGHT
      </div>
    ) : null}
    </>
  );
});

function FieldFrameEvidence({
  hostRef,
  cameraRef,
  sourceFrameNs,
  sourceId,
  selectedPlayerId,
  hullCount,
  territoryCellCount,
  influenceCellCount,
  v3UnitCount,
  v3StableEdgeCount,
  v3StableTriangleCount,
  v3InteractionCount,
  relationMode,
  cameraMode,
  shadowEnabled,
}: {
  readonly hostRef: React.RefObject<HTMLDivElement | null>;
  readonly cameraRef: React.RefObject<FieldCameraHandle | null>;
  readonly sourceFrameNs: bigint | null;
  readonly sourceId: string;
  readonly selectedPlayerId: string | null;
  readonly hullCount: number;
  readonly territoryCellCount: number;
  readonly influenceCellCount: number;
  readonly v3UnitCount: number;
  readonly v3StableEdgeCount: number;
  readonly v3StableTriangleCount: number;
  readonly v3InteractionCount: number;
  readonly relationMode: TacticalRelationMode;
  readonly cameraMode: FieldCameraMode;
  readonly shadowEnabled: boolean;
}) {
  useFrame(() => {
    const host = hostRef.current;
    const camera = cameraRef.current?.getCamera();
    if (!host || !camera) return;
    host.dataset.viewCameraId = camera.uuid;
    host.dataset.cameraProjection = "isOrthographicCamera" in camera && camera.isOrthographicCamera ? "orthographic" : "perspective";
    host.dataset.cameraX = camera.position.x.toFixed(3);
    host.dataset.cameraHeight = camera.position.y.toFixed(2);
    host.dataset.cameraZ = camera.position.z.toFixed(3);
    host.dataset.cameraMode = cameraMode;
    host.dataset.shadowEnabled = String(shadowEnabled);
    host.dataset.orthographicFrustumHeightM = camera instanceof ThreeOrthographicCamera
      ? (host.clientHeight / Math.max(camera.zoom, Number.EPSILON)).toFixed(3)
      : "";
    host.dataset.cameraZoom = camera instanceof ThreeOrthographicCamera ? camera.zoom.toFixed(5) : "";
    const canonicalTimeNs = effectiveTimeNs(useAnalysisStore.getState());
    host.dataset.canonicalTimeNs = canonicalTimeNs?.toString() ?? "";
    host.dataset.drawnFrameNs = sourceFrameNs?.toString() ?? "";
    host.dataset.sourceFrameNs = sourceFrameNs?.toString() ?? "";
    host.dataset.sourceFrameIdentity = sourceFrameNs === null ? "" : sourceId + ":" + sourceFrameNs;
    host.dataset.selectedPlayerId = selectedPlayerId ?? "";
    host.dataset.overlayHulls = String(hullCount);
    host.dataset.overlayTerritoryCells = String(territoryCellCount);
    host.dataset.overlayInfluenceCells = String(influenceCellCount);
    host.dataset.v3UnitCount = String(v3UnitCount);
    host.dataset.v3StableEdgeCount = String(v3StableEdgeCount);
    host.dataset.v3StableTriangleCount = String(v3StableTriangleCount);
    host.dataset.v3InteractionCount = String(v3InteractionCount);
    host.dataset.tacticalRelationMode = relationMode;
  });
  return null;
}

/** Render Field with its own camera inside the shared scissored Canvas viewport. */
function FieldViewRender({
  cameraRef,
  hostRef,
  shadowEnabled,
  shadowUpdateKey,
}: {
  readonly cameraRef: React.RefObject<FieldCameraHandle | null>;
  readonly hostRef: React.RefObject<HTMLDivElement | null>;
  readonly shadowEnabled: boolean;
  readonly shadowUpdateKey: string;
}) {
  const lastShadowUpdateKey = useRef("");
  useFrame(({ gl, scene }) => {
    const camera = cameraRef.current?.getCamera();
    const host = hostRef.current;
    if (!camera || !host) return;
    const hostBounds = host.getBoundingClientRect();
    const canvasBounds = gl.domElement.getBoundingClientRect();
    if (hostBounds.width <= 0 || hostBounds.height <= 0 || canvasBounds.width <= 0 || canvasBounds.height <= 0) return;
    const left = hostBounds.left - canvasBounds.left;
    const bottom = canvasBounds.bottom - hostBounds.bottom;
    if (camera instanceof ThreePerspectiveCamera) {
      camera.aspect = hostBounds.width / hostBounds.height;
      camera.updateProjectionMatrix();
    } else if (camera instanceof ThreeOrthographicCamera) {
      camera.left = hostBounds.width / -2;
      camera.right = hostBounds.width / 2;
      camera.top = hostBounds.height / 2;
      camera.bottom = hostBounds.height / -2;
      camera.updateProjectionMatrix();
    }
    camera.updateMatrixWorld(true);
    gl.shadowMap.enabled = shadowEnabled;
    gl.shadowMap.type = PCFShadowMap;
    gl.shadowMap.autoUpdate = false;
    if (shadowEnabled && shadowUpdateKey !== lastShadowUpdateKey.current) {
      gl.shadowMap.needsUpdate = true;
      lastShadowUpdateKey.current = shadowUpdateKey;
    } else if (!shadowEnabled) {
      lastShadowUpdateKey.current = "";
    }
    const autoClear = gl.autoClear;
    gl.setViewport(left, bottom, hostBounds.width, hostBounds.height);
    gl.setScissor(left, bottom, hostBounds.width, hostBounds.height);
    gl.setScissorTest(true);
    gl.autoClear = true;
    try {
      gl.clear(true, true);
      gl.render(scene, camera);
    } finally {
      gl.autoClear = autoClear;
      gl.setScissorTest(false);
    }
  }, 3);
  return null;
}

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

interface FieldEntityLabelPosition {
  readonly id: string;
  readonly key: string;
  readonly kind: string;
  readonly text: string;
  readonly selected: boolean;
  readonly left: number;
  readonly top: number;
}

const FIELD_LABEL_TARGET_SIZE_PX = 24;
const FIELD_LABEL_LAYOUT_STEP_PX = 30;

function layoutFieldEntityLabels(
  items: readonly FieldEntityLabelPosition[],
  width: number,
  height: number,
): FieldEntityLabelPosition[] {
  const offsets: Array<readonly [number, number]> = [[0, 0]];
  for (let ring = 1; ring <= 8; ring += 1) {
    const distance = ring * FIELD_LABEL_LAYOUT_STEP_PX;
    offsets.push(
      [0, -distance], [distance, 0], [0, distance], [-distance, 0],
      [distance, -distance], [distance, distance], [-distance, distance], [-distance, -distance],
    );
  }
  const placed: Array<{ readonly item: FieldEntityLabelPosition; readonly width: number }> = [];
  const priority = [...items].sort((left, right) =>
    Number(right.selected) - Number(left.selected) || left.id.localeCompare(right.id),
  );
  for (const item of priority) {
    const targetWidth = Math.max(FIELD_LABEL_TARGET_SIZE_PX, item.text.length * 6 + 8);
    const offset = offsets.find(([x, y]) => {
      const left = item.left + x;
      const top = item.top + y;
      if (left < targetWidth / 2 || left > width - targetWidth / 2 ||
        top < FIELD_LABEL_TARGET_SIZE_PX / 2 || top > height - FIELD_LABEL_TARGET_SIZE_PX / 2) return false;
      return placed.every(({ item: other, width: otherWidth }) =>
        Math.abs(left - other.left) >= (targetWidth + otherWidth) / 2 + 2 ||
        Math.abs(top - other.top) >= FIELD_LABEL_TARGET_SIZE_PX + 2,
      );
    });
    const [offsetX, offsetY] = offset ?? [0, 0];
    placed.push({ item: { ...item, left: item.left + offsetX, top: item.top + offsetY }, width: targetWidth });
  }
  return placed.map(({ item }) => item);
}

function FieldEntityLabels({
  hostRef,
  cameraRef,
  buffers,
  frameIndex,
  labels,
  selectedId,
  matchFrame,
}: {
  readonly hostRef: React.RefObject<HTMLDivElement | null>;
  readonly cameraRef: React.RefObject<FieldCameraHandle | null>;
  readonly buffers: TrackingWindowBuffers;
  readonly frameIndex: number;
  readonly labels: ReadonlyMap<string, string>;
  readonly selectedId: string | null;
  readonly matchFrame: MatchFrameContextValue;
}) {
  const [items, setItems] = useState<FieldEntityLabelPosition[]>([]);
  useEffect(() => {
    let request = 0;
    let running = true;
    const update = () => {
      const host = hostRef.current;
      const camera = cameraRef.current?.getCamera();
      if (host && camera && frameIndex >= 0) {
        const bounds = host.getBoundingClientRect();
        const start = buffers.frameOffsets[frameIndex]!;
        const end = buffers.frameOffsets[frameIndex + 1]!;
        camera.updateMatrixWorld(true);
        const next: FieldEntityLabelPosition[] = [];
        for (let row = start; row < end; row += 1) {
          const entityIndex = buffers.entityIndexes[row]!;
          const entityId = buffers.entityIds[entityIndex] ?? "";
          if (!entityId || (buffers.objectKinds[row] ?? TRACKING_KIND.other) === TRACKING_KIND.ball) continue;
          const position = new Vector3(
            buffers.positionsXY[row * 2]!,
          FIELD_RENDER_DEPTH_M.labels,
            -buffers.positionsXY[row * 2 + 1]!,
          ).project(camera);
          if (position.z < -1 || position.z > 1 || position.x < -1 || position.x > 1 || position.y < -1 || position.y > 1) continue;
          next.push({
            id: entityId,
            key: `${entityId}:${row}`,
            kind: trackingKindName(buffers.objectKinds[row] ?? TRACKING_KIND.other),
            text: labels.get(entityId) ?? (entityId.length > 8 ? entityId.slice(-5) : entityId),
            selected: entityId === selectedId,
            left: Math.round(((position.x + 1) * bounds.width / 2) * 10) / 10,
            top: Math.round(((1 - position.y) * bounds.height / 2) * 10) / 10,
          });
        }
        const laidOut = layoutFieldEntityLabels(next, bounds.width, bounds.height);
        setItems((current) => current.length === laidOut.length && current.every((item, index) => {
          const candidate = laidOut[index];
          return candidate !== undefined && item.id === candidate.id && item.selected === candidate.selected && item.left === candidate.left && item.top === candidate.top;
        }) ? current : laidOut);
      } else {
        setItems((current) => current.length === 0 ? current : []);
      }
      if (running) request = window.requestAnimationFrame(update);
    };
    request = window.requestAnimationFrame(update);
    return () => {
      running = false;
      window.cancelAnimationFrame(request);
    };
  }, [buffers, cameraRef, frameIndex, hostRef, labels, matchFrame, selectedId]);
  return (
    <div aria-label="Source-tracked player selection" className="pointer-events-none absolute inset-0 z-10">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          aria-label={`Select ${item.kind} ${item.id}`}
          aria-pressed={item.selected}
          onClick={(event) => {
            event.stopPropagation();
            matchFrame.selectTrackingObject(item.id, item.kind);
          }}
          onMouseEnter={() => matchFrame.hoverTrackingObject(item.id)}
          onMouseLeave={() => matchFrame.hoverTrackingObject(null)}
          className={item.selected
            ? "pointer-events-auto absolute inline-flex min-h-6 min-w-6 items-center justify-center rounded bg-black/85 px-1 py-0.5 text-[10px] font-semibold text-white"
            : "pointer-events-auto absolute inline-flex min-h-6 min-w-6 items-center justify-center rounded bg-black/65 px-1 py-0.5 text-[9px] text-white/85"}
          style={{ left: item.left, top: item.top, transform: "translate(-50%, -50%)" }}
        >
          {item.text}
        </button>
      ))}
    </div>
  );
}

function trackingKindName(kind: number): string {
  if (kind === TRACKING_KIND.player) return "player";
  if (kind === TRACKING_KIND.goalkeeper) return "goalkeeper";
  if (kind === TRACKING_KIND.ball) return "ball";
  if (kind === TRACKING_KIND.official) return "official";
  return "other";
}

interface FieldFunctionalUnitScreenLabel {
  readonly key: string;
  readonly text: string;
  readonly ariaLabel: string;
  readonly selected: boolean;
  readonly color: string;
  readonly left: number;
  readonly top: number;
}

function FieldFunctionalUnitLabels({
  hostRef,
  cameraRef,
  units,
  teamOrder,
  teamLabels,
  homeColor,
  awayColor,
  selectedPlayerId,
}: {
  readonly hostRef: React.RefObject<HTMLDivElement | null>;
  readonly cameraRef: React.RefObject<FieldCameraHandle | null>;
  readonly units: readonly TacticalRow[];
  readonly teamOrder: readonly string[];
  readonly teamLabels: ReadonlyMap<string, string>;
  readonly homeColor: string;
  readonly awayColor: string;
  readonly selectedPlayerId: string | null;
}) {
  const [items, setItems] = useState<FieldFunctionalUnitScreenLabel[]>([]);
  useEffect(() => {
    let request = 0;
    let running = true;
    const project = (xM: number, yM: number, elevationM: number): readonly [number, number] | null => {
      const host = hostRef.current;
      const camera = cameraRef.current?.getCamera();
      if (!host || !camera) return null;
      const bounds = host.getBoundingClientRect();
      const point = new Vector3(xM, elevationM, -yM).project(camera);
      if (point.z < -1 || point.z > 1 || point.x < -1 || point.x > 1 || point.y < -1 || point.y > 1) return null;
      return [
        Math.round(((point.x + 1) * bounds.width / 2) * 10) / 10,
        Math.round(((1 - point.y) * bounds.height / 2) * 10) / 10,
      ];
    };
    const update = () => {
      const camera = cameraRef.current?.getCamera();
      if (camera) {
        camera.updateMatrixWorld(true);
        const next: FieldFunctionalUnitScreenLabel[] = [];
        for (const row of units) {
          const teamId = row["group_id"];
          const role = row["functional_unit"];
          const point = unitPointInSourceFrame(row);
          if (typeof teamId !== "string" || typeof role !== "string" || point === null) continue;
          const screen = project(point[0], point[1], FIELD_RENDER_DEPTH_M.labels);
          if (screen === null) continue;
          const teamName = teamLabels.get(teamId) ?? teamId;
          const memberIds = jsonIds(row["role_ids_json"]);
          const teamIsHome = teamId === teamOrder[0];
          const roleOffset: Readonly<Record<string, readonly [number, number]>> = teamIsHome ? {
            GK: [0, -16],
            DEF: [-26, -17],
            MID: [0, -20],
            ATT: [26, -17],
          } : {
            GK: [0, 16],
            DEF: [26, 17],
            MID: [0, 20],
            ATT: [-26, 17],
          };
          const [offsetX, offsetY] = roleOffset[role] ?? [0, 0];
          next.push({
            key: `unit:${teamId}:${role}`,
            text: role,
            ariaLabel: `${role} functional unit for ${teamName}`,
            selected: selectedPlayerId !== null && memberIds.includes(selectedPlayerId),
            color: teamIsHome ? homeColor : teamId === teamOrder[1] ? awayColor : "#dfe8e4",
            left: screen[0] + offsetX,
            top: screen[1] + offsetY,
          });
        }
        setItems((current) => current.length === next.length && current.every((item, index) => {
          const candidate = next[index];
          return candidate !== undefined && item.key === candidate.key && item.text === candidate.text && item.selected === candidate.selected && item.left === candidate.left && item.top === candidate.top;
        }) ? current : next);
      } else {
        setItems((current) => current.length === 0 ? current : []);
      }
      if (running) request = window.requestAnimationFrame(update);
    };
    request = window.requestAnimationFrame(update);
    return () => {
      running = false;
      window.cancelAnimationFrame(request);
    };
  }, [awayColor, cameraRef, homeColor, hostRef, selectedPlayerId, teamLabels, teamOrder, units]);
  return (
    <div aria-label="Functional unit anchors and inter-line gaps" className="pointer-events-none absolute inset-0 z-10">
      {items.map((item) => (
        <span
          key={item.key}
          data-testid="field-functional-unit-label"
          role="note"
          aria-label={item.ariaLabel}
          title={item.ariaLabel}
          className={item.selected
            ? "pointer-events-none absolute rounded border border-white bg-white px-1 py-0.5 text-[9px] font-bold text-black shadow"
            : "pointer-events-none absolute rounded border border-white/70 bg-black/85 px-1 py-0.5 text-[9px] font-semibold text-white shadow"}
          style={{ left: item.left, top: item.top, transform: "translate(-50%, -50%)", borderColor: item.selected ? "#ffffff" : item.color }}
        >
          {item.text}
        </span>
      ))}
    </div>
  );
}

function SceneReady({ onReady }: { readonly onReady: () => void }) {
  useEffect(() => onReady(), [onReady]);
  return null;
}

const FieldCamera = forwardRef<FieldCameraHandle, {
  readonly mode: FieldCameraMode;
  readonly onModeChange: (mode: FieldCameraMode) => void;
  readonly cameraDistance: number;
  readonly dimensions: { readonly lengthM: number; readonly widthM: number } | null;
  readonly hostRef: React.RefObject<HTMLDivElement | null>;
}>(function FieldCamera({ mode, onModeChange, cameraDistance, dimensions, hostRef }, ref) {
  const [viewportSize, setViewportSize] = useState({ width: 1, height: 1 });
  const [perspectiveCamera, setPerspectiveCamera] = useState<PerspectiveCameraType | null>(null);
  const [orthographicCamera, setOrthographicCamera] = useState<OrthographicCameraType | null>(null);
  const invalidate = useThree((state) => state.invalidate);
  const controlsRef = useRef<React.ElementRef<typeof CameraControls> | null>(null);
  const activeCamera = mode === "perspective" ? perspectiveCamera : orthographicCamera;
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    const update = () => {
      const bounds = host.getBoundingClientRect();
      if (bounds.width <= 0 || bounds.height <= 0) return;
      setViewportSize((current) => current.width === bounds.width && current.height === bounds.height
        ? current
        : { width: bounds.width, height: bounds.height });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(host);
    return () => observer.disconnect();
  }, [hostRef]);
  const viewportAspect = viewportSize.width / Math.max(viewportSize.height, 1);
  const mapFitHeightM = dimensions === null
    ? cameraDistance * 0.72
    : Math.max(dimensions.widthM * 1.08, dimensions.lengthM / Math.max(0.1, viewportAspect) * 1.08);
  const structureFitHeightM = mapFitHeightM * 1.42;
  // The view's orthographic frustum is measured in viewport pixels; zoom maps
  // those pixels back to the source pitch dimensions in metres.
  const topDownZoom = viewportSize.height / mapFitHeightM;
  const structureLiftZoom = viewportSize.height / structureFitHeightM;
  const perspectiveFitDistance = dimensions === null
    ? cameraDistance
    : (dimensions.lengthM + dimensions.widthM * 0.1) * 1.1 /
      (2 * Math.tan((42 * Math.PI) / 360) * viewportAspect);
  const perspectiveBaseDistance = Math.hypot(
    cameraDistance * 1.4 * 0.53,
    (dimensions?.widthM ?? cameraDistance / 1.5) * 1.5,
    (dimensions?.lengthM ?? 0) * 0.08,
  );
  const perspectiveFitScale = Math.max(1, perspectiveFitDistance / perspectiveBaseDistance);
  /* eslint-disable react-hooks/immutability -- R3F cameras are mutable renderer state and this callback intentionally poses the active camera. */
  const viewPose = useCallback((nextMode: FieldCameraMode, targetX = 0, targetZ = 0) => {
    const isOrthographic = nextMode !== "perspective";
    const isTacticalMap = nextMode === "tactical-map";
    const camera = isOrthographic ? orthographicCamera : perspectiveCamera;
    if (camera === null) return;
    const lengthM = dimensions?.lengthM ?? cameraDistance;
    const widthM = dimensions?.widthM ?? cameraDistance / 1.5;
    const perspectiveScale = perspectiveFitScale;
    const cameraX = isTacticalMap
      ? targetX
      : targetX + (nextMode === "structure-lift" ? lengthM * 0.4 : lengthM * 0.08) * perspectiveScale;
    const cameraY = isTacticalMap
      ? cameraDistance * 1.2
      : nextMode === "structure-lift"
        ? cameraDistance * 0.95
        : cameraDistance * 1.4 * 0.53 * perspectiveScale;
    const cameraZ = isTacticalMap
      ? targetZ
      : targetZ + (nextMode === "structure-lift" ? widthM * 1.35 : widthM * 1.5) * perspectiveScale;
    camera.up.set(0, 0, -1);
    if ("isPerspectiveCamera" in camera) {
      camera.aspect = viewportAspect;
      camera.near = 0.1;
      camera.fov = 42;
      camera.far = cameraDistance * 6;
    }
    if ("isOrthographicCamera" in camera && isOrthographic) {
      camera.zoom = isTacticalMap ? topDownZoom : structureLiftZoom;
      void controlsRef.current?.zoomTo(camera.zoom, false);
    }
    camera.position.set(cameraX, cameraY, cameraZ);
    camera.lookAt(targetX, 0, targetZ);
    camera.updateMatrixWorld(true);
    camera.updateProjectionMatrix();
    void controlsRef.current?.setLookAt(cameraX, cameraY, cameraZ, targetX, 0, targetZ, false);
    invalidate();
  }, [cameraDistance, dimensions, invalidate, orthographicCamera, perspectiveCamera, perspectiveFitScale, structureLiftZoom, topDownZoom, viewportAspect]);
  /* eslint-enable react-hooks/immutability */
  const resetView = useCallback(() => viewPose(mode), [mode, viewPose]);
  const setCameraMode = useCallback((nextMode: FieldCameraMode) => onModeChange(nextMode), [onModeChange]);
  const focusAt = useCallback((xM: number, zM: number) => viewPose(mode, xM, zM), [mode, viewPose]);
  useImperativeHandle(ref, () => ({ resetView, setCameraMode, focusAt, getCamera: () => activeCamera }), [activeCamera, focusAt, resetView, setCameraMode]);
  useEffect(() => resetView(), [resetView]);
  return (
    <>
      <PerspectiveCamera ref={setPerspectiveCamera} position={[0, cameraDistance, 0]} aspect={viewportAspect} fov={42} near={0.1} far={cameraDistance * 6} />
      <OrthographicCamera ref={setOrthographicCamera} position={[0, cameraDistance, 0]} up={[0, 0, -1]} zoom={topDownZoom} near={0.1} far={cameraDistance * 6} />
      {activeCamera !== null ? (
        <CameraControls
          ref={controlsRef}
          camera={activeCamera}
          makeDefault
          minDistance={cameraDistance * 0.3}
          maxDistance={cameraDistance * 3}
          minPolarAngle={mode === "tactical-map" ? 0 : 0.08}
          maxPolarAngle={mode === "tactical-map" ? 0.001 : mode === "structure-lift" ? 1.18 : Math.PI}
          smoothTime={0.18}
        />
      ) : null}
    </>
  );
});
