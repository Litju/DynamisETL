import type { TrackingWindowBuffers } from "@/components/matchlab/frame-buffers";
import type { PitchEvent, PitchLayers, TacticalOverlay } from "@/components/matchlab/render-types";
import type { TrailPoint } from "@/components/pitch/pitch-model";

export interface PitchPalette {
  readonly surface: string;
  readonly pitchLine: string;
  readonly home: string;
  readonly away: string;
  readonly ball: string;
  readonly official: string;
  readonly extrapolated: string;
  readonly selection: string;
  readonly trail: string;
  readonly label: string;
  readonly event: string;
  /** Dark (or light, in Report Light) halo that keeps the ball above overlays. */
  readonly halo: string;
}

export interface PitchRendererHandle {
  setFrame(
    buffers: TrackingWindowBuffers,
    frameIndex: number,
    selectedId: string | null,
    teamOrder: readonly string[],
  ): void;
  setTrail(trail: readonly TrailPoint[], selectedId: string | null): void;
  setEvents(events: readonly PitchEvent[]): void;
  /** Registered short labels (e.g. shirt numbers) by object id. */
  setEntityLabels?(labels: ReadonlyMap<string, string>): void;
  setTacticalOverlay(overlay: TacticalOverlay): void;
  setLayers(layers: PitchLayers): void;
  resetView(): void;
  destroy(): void;
}
