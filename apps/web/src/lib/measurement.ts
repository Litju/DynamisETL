/**
 * Scientific language rules.
 *
 * Measurement class and quality are always expressed with text + shape + color;
 * color never carries meaning alone, and copy never upgrades a source/model
 * estimate into measurement or ground truth.
 */

export type MeasurementClass =
  | "RAW_MEASURED"
  | "SOURCE_DERIVED"
  | "PIPELINE_DERIVED"
  | "MODEL_ESTIMATED";

export type MeasurementShape = "circle" | "diamond" | "square" | "triangle";

export interface MeasurementClassDescriptor {
  readonly id: MeasurementClass;
  readonly label: string;
  readonly shortLabel: string;
  readonly shape: MeasurementShape;
  readonly token: string;
  readonly semantics: string;
  readonly neverMeans: readonly string[];
}

export const MEASUREMENT_CLASSES: Record<MeasurementClass, MeasurementClassDescriptor> = {
  RAW_MEASURED: {
    id: "RAW_MEASURED",
    label: "Raw measured",
    shortLabel: "raw",
    shape: "circle",
    token: "var(--d-measurement-raw)",
    semantics: "Directly measured instrument signal.",
    neverMeans: ["Raw measured is not automatically valid: quality context still applies."],
  },
  SOURCE_DERIVED: {
    id: "SOURCE_DERIVED",
    label: "Source-derived reference",
    shortLabel: "source-derived",
    shape: "diamond",
    token: "var(--d-measurement-source-derived)",
    semantics: "Computed by the source/provider from its own measurements.",
    neverMeans: [
      "Source-derived is not ground truth.",
      "A source-derived reference has no established interchangeability with this pipeline.",
    ],
  },
  PIPELINE_DERIVED: {
    id: "PIPELINE_DERIVED",
    label: "Pipeline-derived",
    shortLabel: "pipeline-derived",
    shape: "square",
    token: "var(--d-measurement-pipeline-derived)",
    semantics: "Computed by a versioned DynamisData processor from canonical inputs.",
    neverMeans: ["Pipeline-derived is not a direct measurement."],
  },
  MODEL_ESTIMATED: {
    id: "MODEL_ESTIMATED",
    label: "Model-estimated",
    shortLabel: "model-estimated",
    shape: "triangle",
    token: "var(--d-measurement-model-estimated)",
    semantics: "Estimated by a provider model; never a raw instrument measurement.",
    neverMeans: [
      "Model-estimated is not measured.",
      "A provider p90 error radius is not a confidence interval or probability.",
    ],
  },
};

export type QualityState = "valid" | "warning" | "quarantined" | "unavailable";

export interface QualityStateDescriptor {
  readonly id: QualityState;
  readonly label: string;
  readonly token: string;
  readonly glyph: string;
}

export const QUALITY_STATES: Record<QualityState, QualityStateDescriptor> = {
  valid: { id: "valid", label: "Valid", token: "var(--d-quality-valid)", glyph: "●" },
  warning: { id: "warning", label: "Warning", token: "var(--d-quality-warning)", glyph: "▲" },
  quarantined: {
    id: "quarantined",
    label: "Quarantined",
    token: "var(--d-quality-error)",
    glyph: "■",
  },
  unavailable: {
    id: "unavailable",
    label: "Unavailable",
    token: "var(--d-quality-unavailable)",
    glyph: "—",
  },
};

/** Map an API severity/state pair without upgrading or hiding anything. */
export function qualityStateFor(severity: string, state: string): QualityState {
  if (state === "QUARANTINED") return "quarantined";
  if (severity === "ERROR") return "quarantined";
  if (severity === "WARNING") return "warning";
  if (severity === "INFO") return "valid";
  return "unavailable";
}

export interface MetricDisplay {
  readonly text: string;
  readonly valueText: string;
  readonly unitText: string;
}

/**
 * Deterministic metric formatting: fixed significant digits, no locale
 * grouping, unit appended explicitly. Never turn a statistic into a percentage
 * claim the backend did not make.
 */
export function formatMetricValue(value: number | null, siUnit: string): MetricDisplay {
  if (value === null || !Number.isFinite(value)) {
    return { text: "unavailable", valueText: "—", unitText: siUnit };
  }
  const magnitude = Math.abs(value);
  let digits: number;
  if (magnitude === 0) digits = 3;
  else if (magnitude >= 1000) digits = 1;
  else if (magnitude >= 1) digits = 3;
  else digits = Math.max(3, 2 - Math.floor(Math.log10(magnitude)));
  const valueText = value.toFixed(Math.min(12, digits));
  return {
    text: siUnit === "1" ? valueText : `${valueText} ${siUnit}`,
    valueText,
    unitText: siUnit,
  };
}

/** The locked wording for provider error radii. */
export const ERROR_RADIUS_LABEL = "provider p90 predicted error radius";
/** The locked wording for statistical associations. */
export const ASSOCIATION_LABEL = "descriptive association";
/** The locked wording for cross-source comparability. */
export const INTERCHANGEABILITY_NOTE = "interchangeability not established";
