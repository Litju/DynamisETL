import { Pitch3D } from "@/components/matchlab/Pitch3D";
import {
  TrackingLayer,
  type TrackingLayerPalette,
} from "@/components/matchlab/TrackingLayer";
import { trackingBuffersFromFrames } from "@/components/matchlab/frame-buffers";
import { ContextLayer, type ContextSubject, type SourceAlignmentDisplay } from "@/components/matchlab/ContextLayer";
import { TacticalLayer, type TacticalLayerPalette } from "@/components/matchlab/TacticalLayer";
import type { PitchEvent, TacticalOverlay } from "@/components/matchlab/render-types";
import type { PoseLayerProps } from "@/components/pose/PoseScene";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import type { TrackingFrame } from "@/components/pitch/pitch-model";
import type { TrailPoint } from "@/components/pitch/pitch-model";
import { PoseLayer } from "@/components/pose/PoseScene";
import { useMemo } from "react";

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
  readonly trackingFrames: readonly TrackingFrame[];
  readonly trackingMaxAgeNs: number;
  readonly teamOrder: readonly string[];
  readonly trackingPalette: TrackingLayerPalette;
  readonly tacticalOverlay: TacticalOverlay;
  readonly events: readonly PitchEvent[];
  readonly tacticalPalette: TacticalLayerPalette;
  readonly poseLayer: PoseLayerProps | null;
  readonly context: {
    readonly selected: ContextSubject | null;
    readonly hovered?: ContextSubject | null;
    readonly trail?: readonly TrailPoint[];
    readonly alignment?: SourceAlignmentDisplay | null;
    readonly displayMode?: string;
  };
}

/** Scene composition only. A viewport supplies the camera and the shared Canvas. */
export function MatchWorld({
  matchFrame,
  visibility,
  trackingFrames,
  trackingMaxAgeNs,
  teamOrder,
  trackingPalette,
  tacticalOverlay,
  events,
  tacticalPalette,
  poseLayer,
  context,
}: MatchWorldProps) {
  const trackingBuffers = useMemo(
    () => trackingBuffersFromFrames(trackingFrames),
    [trackingFrames],
  );
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
        events={events}
        matchFrame={matchFrame}
        palette={tacticalPalette}
        visible={visibility.tactical}
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
