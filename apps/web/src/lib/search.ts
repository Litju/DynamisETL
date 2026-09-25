/**
 * Durable analysis state schemas.
 *
 * TanStack Router owns shareable analytical context. Every search parameter is
 * validated here with Zod, so a hand-edited or stale URL degrades to a safe
 * default instead of entering the state spine as an unchecked value.
 */

import { z } from "zod";

/** Canonical time is signed; see `lib/time.ts` for why. */
export const DECIMAL_NS = /^-?\d+$/;

export const WORKBENCH_VIEWS = ["overview", "signals", "field", "pose", "split", "provenance"] as const;
export type WorkbenchView = (typeof WORKBENCH_VIEWS)[number];
export const TACTICAL_VIEWS = ["live", "structure", "relations", "space", "events", "range", "report"] as const;
export type TacticalView = (typeof TACTICAL_VIEWS)[number];

export const MODALITIES = [
  "gnss",
  "imu",
  "force",
  "lpt",
  "tracking",
  "event",
  "pose",
] as const;
export type Modality = (typeof MODALITIES)[number];

// The router query-string decoder coerces numeric-looking values to numbers
// before validation (`t_ns=2987480000000` arrives as a number). Values are
// normalized back to canonical decimal text; an unsafe integer fails closed.
const nsText = z.preprocess((value) => {
  if (typeof value === "number") {
    return Number.isSafeInteger(value) ? String(value) : undefined;
  }
  if (typeof value === "string") {
    return DECIMAL_NS.test(value) ? value : undefined;
  }
  return undefined;
}, z.string().optional());

const optionalText = z.preprocess((value) => {
  if (typeof value === "string" && value.length > 0) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return undefined;
}, z.string().optional());

export const labSearchSchema = z.object({
  trial: optionalText,
  subject: optionalText,
  stream: optionalText,
  metric: optionalText,
  /** Exact served result (derived_metric_id) the inspector follows. */
  result: optionalText,
  entity: optionalText,
  t_ns: nsText,
  from_ns: nsText,
  to_ns: nsText,
  range_ns: nsText,
  view: z.enum(WORKBENCH_VIEWS).catch("overview").default("overview"),
  tactical: z.enum(TACTICAL_VIEWS).optional().catch(undefined),
  compare: optionalText,
});
export type LabSearch = z.infer<typeof labSearchSchema>;

export const catalogSearchSchema = z.object({
  q: optionalText,
  modality: z.enum(MODALITIES).optional().catch(undefined),
  rights: z.enum(["all", "commercial", "noncommercial"]).optional().catch("all"),
  dataset: optionalText,
});
export type CatalogSearch = z.infer<typeof catalogSearchSchema>;

export const compareSearchSchema = z.object({
  a: optionalText,
  b: optionalText,
  metric: optionalText,
  view: z.enum(WORKBENCH_VIEWS).catch("signals").default("signals"),
});
export type CompareSearch = z.infer<typeof compareSearchSchema>;

export const methodsSearchSchema = z.object({
  metric: optionalText,
  dataset: optionalText,
  /** Exact served result whose selected lineage the page renders. */
  result: optionalText,
});
export type MethodsSearch = z.infer<typeof methodsSearchSchema>;

export const runsSearchSchema = z.object({
  dataset: optionalText,
  run: optionalText,
});
export type RunsSearch = z.infer<typeof runsSearchSchema>;

export const qualitySearchSchema = z.object({
  dataset: optionalText,
  session: optionalText,
  severity: z.enum(["INFO", "WARNING", "ERROR"]).optional().catch(undefined),
});
export type QualitySearch = z.infer<typeof qualitySearchSchema>;

/**
 * Parse router search input into a validated object, dropping unknown keys.
 * The result is always safe to serialize back into the URL.
 */
export function parseSearch<Schema extends z.ZodType>(
  schema: Schema,
  input: Record<string, unknown>,
): z.infer<Schema> {
  const result = schema.safeParse(input);
  if (result.success) {
    return result.data;
  }
  return schema.parse({});
}

/** Normalize raw router search values before they enter the shared context. */
export function normalizeLabSearch(input: unknown): LabSearch {
  const record =
    typeof input === "object" && input !== null
      ? (input as Record<string, unknown>)
      : {};
  return parseSearch(labSearchSchema, record);
}

/** Build lab search from a partial durable context without undefined keys. */
export function labSearchToParams(search: LabSearch): Record<string, string> {
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === "string" && value.length > 0) {
      params[key] = value;
    }
  }
  return params;
}
