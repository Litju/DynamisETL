/**
 * Presentation-only world-Y offsets, measured from the pitch plane in metres.
 * None of these values are scientific Z coordinates. Keep layer depth here so
 * tracking, tactical geometry, labels, and contours share one depth authority.
 */
export const FIELD_RENDER_DEPTH_M = {
  pitchSurface: 0,
  pitchMarkings: 0.006,
  hullFill: 0.008,
  territoryFill: 0.01,
  trailPath: 0.011,
  groundRing: 0.012,
  alignmentLine: 0.013,
  trackingMarker: 0.014,
  scalarFlat: 0.016,
  scalarContour: 0.018,
  shapeOutline: 0.019,
  structureSpine: 0.02,
  structureNode: 0.022,
  stableGraph: 0.024,
  localTriangle: 0.026,
  attackerDefender: 0.028,
  eventPath: 0.03,
  sourceEvent: 0.032,
  labels: 0.034,
  alignmentLabel: 0.036,
  elevatedSurfaceBaseline: 0.016,
  ballCenter: 0.16,
  pitchEdgeCenter: -0.18,
  pitchEdgeThickness: 0.32,
} as const;
