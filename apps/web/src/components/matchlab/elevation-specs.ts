import type { ElevationSpec, ScalarFieldSpec } from "@/components/matchlab/ScalarFieldLayer";
import { FIELD_RENDER_DEPTH_M } from "@/components/matchlab/render-layer-depths";

/** RES-110 arrival_time_s domain for the versioned kinematic model. */
export const ARRIVAL_TIME_DOMAIN = { min: 0, max: 5 } as const;

/** Presentation contract for the only currently served elevated scalar metric. */
export const ARRIVAL_TIME_ELEVATION_SPEC: ElevationSpec = {
  metricId: "tactical.player.arrival_time",
  measurementClass: "MODEL_ESTIMATED",
  scientificDomain: ARRIVAL_TIME_DOMAIN,
  units: "s",
  elevationTransform: {
    kind: "linear-domain",
    direction: "decreasing",
    meaning: "Earlier projected arrival (lower seconds) maps to greater analytical elevation.",
  },
  displayHeightLimitM: 1.8,
  baseline: { meaning: "pitch-plane-offset", offsetM: FIELD_RENDER_DEPTH_M.elevatedSurfaceBaseline },
  colorDomain: ARRIVAL_TIME_DOMAIN,
  legendCopy: "Arrival time (s) · lower values mean earlier projected arrival and a higher analytical surface.",
};

export const ARRIVAL_TIME_FIELD_SPEC: ScalarFieldSpec = {
  metricId: ARRIVAL_TIME_ELEVATION_SPEC.metricId,
  method: "tactical.arrival_time v1 kinematic model",
  unit: ARRIVAL_TIME_ELEVATION_SPEC.units,
  measurementClass: ARRIVAL_TIME_ELEVATION_SPEC.measurementClass,
  domain: ARRIVAL_TIME_DOMAIN,
  mode: "heatmap",
  contourLevels: [1, 2, 3, 4],
  elevationSpec: ARRIVAL_TIME_ELEVATION_SPEC,
};

export function describeElevationSpec(spec: ElevationSpec): string {
  const scientificDomain = `${spec.scientificDomain.min}–${spec.scientificDomain.max} ${spec.units}`;
  const colorDomain = `${spec.colorDomain.min}–${spec.colorDomain.max} ${spec.units}`;
  return `${spec.metricId}; scientific domain ${scientificDomain}; ${spec.elevationTransform.meaning} Display height 0–${spec.displayHeightLimitM} m from the pitch-plane baseline; color domain ${colorDomain}. ${spec.legendCopy}`;
}
