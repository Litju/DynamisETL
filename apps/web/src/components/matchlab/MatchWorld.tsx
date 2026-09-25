import { Pitch3D } from "@/components/matchlab/Pitch3D";
import {
  TrackingLayer,
  type TrackingLayerPalette,
} from "@/components/matchlab/TrackingLayer";
import type { TacticalGridWindowBuffers, TrackingWindowBuffers } from "@/components/matchlab/frame-buffers";
import type { TacticalV3Frame } from "@/components/pitch/tactical-v3";
import { ContextLayer, type ContextSubject, type SourceAlignmentDisplay } from "@/components/matchlab/ContextLayer";
import { TacticalLayer, type TacticalLayerPalette } from "@/components/matchlab/TacticalLayer";
import { ScalarFieldLayer, type ScalarFieldSpec } from "@/components/matchlab/ScalarFieldLayer";
import type { PitchEvent, PitchLayers, TacticalOverlay } from "@/components/matchlab/render-types";
import type { PoseLayerProps } from "@/components/pose/PoseScene";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import type { TrailPoint } from "@/components/pitch/pitch-model";
import { PoseLayer } from "@/components/pose/PoseScene";
import type { TacticalRelationMode } from "@/lib/state/analysis";

export interface MatchLayerVisibility {
  readonly pitch: boolean;
  readonly tracking: boolean;
  readonly tactical: boolean;
  readonly pose: boolean;
  readonly context: boolean;
}

export interface MatchWorldProps {
  readonly matchFrame: MatchFrameContextValue;
  readonly visibility: MatchLayerVisibility;
  readonly trackingBuffers: TrackingWindowBuffers | null;
  readonly trackingMaxAgeNs: number;
  readonly teamOrder: readonly string[];
  readonly trackingPalette: TrackingLayerPalette;
  readonly tacticalOverlay: TacticalOverlay;
  readonly tacticalV3: TacticalV3Frame;
  readonly tacticalRelationMode: TacticalRelationMode;
  readonly trackingFrameIndex: number;
  readonly tacticalLayers: Pick<PitchLayers, "events" | "geometry" | "territory" | "influence">;
  readonly scalarField: {
    readonly buffers: TacticalGridWindowBuffers | null;
    readonly spec: ScalarFieldSpec;
    readonly maxAgeNs: number;
    readonly visible: boolean;
    readonly castShadow: boolean;
    readonly onElevationUpdate?: (state: { readonly valid: boolean; readonly vertexCount: number; readonly gridTimeNs: bigint | null }) => void;
  };
  readonly events: readonly PitchEvent[];
  readonly tacticalPalette: TacticalLayerPalette;
  readonly poseLayer: PoseLayerProps | null;
  readonly context: {
    readonly selected: ContextSubject | null;
    readonly hovered?: ContextSubject | null;
    readonly trail?: readonly TrailPoint[];
    readonly alignment?: SourceAlignmentDisplay | null;
  };
}

/** Scene composition only. A viewport supplies the camera and the shared Canvas. */
export function MatchWorld({
  matchFrame,
  visibility,
  trackingBuffers,
  trackingMaxAgeNs,
  teamOrder,
  trackingPalette,
  tacticalOverlay,
  tacticalV3,
  tacticalRelationMode,
  trackingFrameIndex,
  tacticalLayers,
  scalarField,
  events,
  tacticalPalette,
  poseLayer,
  context,
}: MatchWorldProps) {
  const poseMaxAgeNs = matchFrame.poseSource?.nominalRateHz
    ? 1.5 * (1e9 / matchFrame.poseSource.nominalRateHz)
    : 0;
  const pitchDimensions = matchFrame.trackingSource?.pitchDimensionsM ?? null;

  return (
    <group name="MatchWorld">
      {visibility.pitch && pitchDimensions !== null ? (
        <Pitch3D dimensions={pitchDimensions} />
      ) : null}
      <TrackingLayer
        frameBuffers={trackingBuffers}
        matchFrame={matchFrame}
        teamOrder={teamOrder}
        palette={trackingPalette}
        maxAgeNs={trackingMaxAgeNs}
        sourceId={matchFrame.trackingSource?.artifactId ?? matchFrame.trackingSource?.streamId ?? "tracking"}
        visible={visibility.tracking}
      />
      <TacticalLayer
        overlay={tacticalOverlay}
        tacticalV3={tacticalV3}
        events={events}
        matchFrame={matchFrame}
        palette={tacticalPalette}
        relationMode={tacticalRelationMode}
        trackingBuffers={trackingBuffers}
        trackingFrameIndex={trackingFrameIndex}
        layers={{ ...tacticalLayers, influence: false }}
        visible={visibility.tactical}
      />
      <ScalarFieldLayer
        buffers={scalarField.buffers}
        spec={scalarField.spec}
        matchFrame={matchFrame}
        maxAgeNs={scalarField.maxAgeNs}
        visible={visibility.tactical && scalarField.visible}
        castShadow={scalarField.castShadow}
        {...(scalarField.onElevationUpdate ? { onElevationUpdate: scalarField.onElevationUpdate } : {})}
      />
      {visibility.pose && poseLayer !== null ? (
        <PoseLayer
          {...poseLayer}
          selectedSubjectId={matchFrame.selectedPlayerId}
          maxFrameGapNs={poseMaxAgeNs}
          sourceStreamId={matchFrame.poseSource?.streamId}
          sourceArtifactId={matchFrame.poseSource?.artifactId}
          reportResolvedFrame={matchFrame.reportResolvedFrame}
        />
      ) : null}
      {visibility.context ? (
        <ContextLayer {...context} />
      ) : null}
    </group>
  );
}
