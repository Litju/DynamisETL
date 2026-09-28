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

export const WORKBENCH_VIEWS = ["overview", "signals", "field", "pose", "matchlab", "provenance"] as const;
export type WorkbenchView = (typeof WORKBENCH_VIEWS)[number];
export const TACTICAL_VIEWS = ["live", "structure", "relations", "space", "events", "range", "report"] as const;
export type TacticalView = (typeof TACTICAL_VIEWS)[number];

const workbenchViewSchema = z.preprocess(
  (value) => value === "split" ? "matchlab" : value,
  z.enum(WORKBENCH_VIEWS).catch("overview").default("overview"),
);
const compareViewSchema = z.preprocess(
  (value) => value === "split" ? "matchlab" : value,
  z.enum(WORKBENCH_VIEWS).catch("signals").default("signals"),
);

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
  view: workbenchViewSchema,
  tactical: z.enum(TACTICAL_VIEWS).optional().catch(undefined),
  compare: optionalText,
});
export type LabSearch = z.infer<typeof labSearchSchema>;

export const catalogSearchSchema = z.object({
  q: optionalText,
  modality: z.enum(MODALITIES).optional().catch(undefined),
  rights: z.enum(["all", "commercial", "noncommercial", "local_only"]).optional().catch("all"),
  dataset: optionalText,
  sport: optionalText,
  provider: optionalText,
  kind: z.enum(["contest", "competition_edition", "performance_dataset", "performance_session"]).optional().catch(undefined),
});
export type CatalogSearch = z.infer<typeof catalogSearchSchema>;

export const compareSearchSchema = z.object({
  a: optionalText,
  b: optionalText,
  metric: optionalText,
  view: compareViewSchema,
});
export type CompareSearch = z.infer<typeof compareSearchSchema>;

export const SEASON_FAMILIES = ["physical", "obr", "passing", "shots", "drives", "picks"] as const;
export type SeasonFamily = (typeof SEASON_FAMILIES)[number];
export const SEASON_POPULATIONS = ["position", "edition", "team"] as const;
export type SeasonPopulation = (typeof SEASON_POPULATIONS)[number];
export const SEASON_VIEWS = ["profile", "table"] as const;

const minMatchesText = z.preprocess((value) => {
  const numeric = typeof value === "string" ? Number(value) : value;
  return typeof numeric === "number" && Number.isInteger(numeric) && numeric >= 1 && numeric <= 100
    ? String(numeric)
    : undefined;
}, z.string().optional());

/**
 * SeasonLab durable context: edition → team → player → metric family, plus the
 * explicit comparison denominator. Nothing here is a playhead; season grain has
 * no canonical time.
 */
export const seasonSearchSchema = z.object({
  edition: optionalText,
  family: z.enum(SEASON_FAMILIES).optional().catch(undefined),
  team: optionalText,
  player: optionalText,
  pos: optionalText,
  population: z.enum(SEASON_POPULATIONS).optional().catch(undefined),
  min: minMatchesText,
  /** Comma-separated metric columns; empty means the family's default panel. */
  metrics: optionalText,
  focus: optionalText,
  compare: optionalText,
  q: optionalText,
  view: z.enum(SEASON_VIEWS).optional().catch(undefined),
});
export type SeasonSearch = z.infer<typeof seasonSearchSchema>;

export const basketballSpatialSearchSchema = z.object({
  contest: optionalText,
  period: z.preprocess((value) => {
    const numeric = typeof value === "string" ? Number(value) : value;
    return typeof numeric === "number" && Number.isInteger(numeric) && numeric >= 1 && numeric <= 20
      ? String(numeric)
      : undefined;
  }, z.string().optional()),
  frame: z.preprocess((value) => {
    const numeric = typeof value === "string" ? Number(value) : value;
    return typeof numeric === "number" && Number.isSafeInteger(numeric) && numeric >= 0
      ? String(numeric)
      : undefined;
  }, z.string().optional()),
  event: optionalText,
  player: optionalText,
  entity: optionalText,
});
export type BasketballSpatialSearch = z.infer<typeof basketballSpatialSearchSchema>;

export const GAME_BOX_VIEWS = ["player", "team"] as const;

/**
 * GameLab's durable context is owned by the router, using the V4 edition,
 * contest, ContestPeriod, Team and Subject identifiers. Clock stays explicit
 * in the URL because source clocks differ by sport and period.
 */
export const gameSearchSchema = z.object({
  edition: optionalText,
  game: optionalText,
  team: optionalText,
  period: z.preprocess((value) => {
    const numeric = typeof value === "string" ? Number(value) : value;
    return typeof numeric === "number" && Number.isInteger(numeric) && numeric >= 1 && numeric <= 20
      ? String(numeric)
      : undefined;
  }, z.string().optional()),
  clock: optionalText,
  event: optionalText,
  player: optionalText,
  q: optionalText,
  offset: z.preprocess((value) => {
    const numeric = typeof value === "string" ? Number(value) : value;
    return typeof numeric === "number" && Number.isInteger(numeric) && numeric >= 0
      ? String(numeric)
      : undefined;
  }, z.string().optional()),
  box: z.enum(GAME_BOX_VIEWS).optional().catch(undefined),
});
export type GameSearch = z.infer<typeof gameSearchSchema>;

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
