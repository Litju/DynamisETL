/**
 * SeasonLab presentation model.
 *
 * Pure functions over served season contracts: default metric panels, grouping,
 * number formatting and the reproducible season-profile report. Nothing here
 * computes a scientific value; ranks and percentiles come from the API, which
 * names the population they are relative to.
 */

import type {
  SeasonEditionView,
  SeasonFamilyRef,
  SeasonMetricView,
  SeasonProfileView,
  SeasonRankedMetricView,
} from "@/api/types";
import type { SeasonFamily, SeasonPopulation } from "@/lib/search";

/** Curated first-screen panels; every other registered metric is one pick away. */
export const DEFAULT_SEASON_METRICS: Record<SeasonFamily, readonly string[]> = {
  physical: [
    "total_distance_full_all",
    "total_metersperminute_full_all",
    "running_distance_full_all",
    "hsr_distance_full_all",
    "sprint_distance_full_all",
    "sprint_count_full_all",
    "hi_count_full_all",
    "highaccel_count_full_all",
    "highdecel_count_full_all",
    "explacceltosprint_count_full_all",
    "psv99",
  ],
  obr: [
    "offballrun_count_p30tip",
    "behindrun_count_p30tip",
    "comingshortrun_count_p30tip",
    "aheadoftheballrun_count_p30tip",
    "supportrun_count_p30tip",
    "offballrun_count_targeted_p30tip",
    "offballrun_count_received_p30tip",
    "offballrun_count_dangerous_p30tip",
    "offballrun_count_shotwithin10s_p30tip",
    "offballrun_avgdistance",
  ],
  passing: [
    "pass_count_attempted_p30tip",
    "pass_pct_completed",
    "pass_avgxpass_attempted",
    "pass_count_linebreak_attempted_p30tip",
    "pass_count_linebreak_completed_p30tip",
    "pass_count_torun_attempted_p30tip",
    "pass_count_dangerous_attempted_p30tip",
    "pass_count_difficultpass_attempted_p30tip",
    "pass_count_shotwithin10s_p30tip",
    "pass_avgdistance",
  ],
  shots: [
    "attempts",
    "mades",
    "total_points",
    "fg_percentage",
    "three_pt_percentage",
    "avg_attempts_distance",
    "rim_attempts",
    "rim_mades",
  ],
  drives: [
    "total_drives",
    "successful_drives",
    "made_baskets",
    "assists",
    "potential_assists",
    "fouls",
    "points_per_drive",
  ],
  picks: [
    "handler_total_picks",
    "handler_points",
    "handler_assists",
    "handler_fouls",
    "screener_total_picks",
    "screener_points",
    "screener_assists",
    "screener_fouls",
  ],
};

export const FAMILY_ORDER: readonly SeasonFamily[] = [
  "physical",
  "obr",
  "passing",
  "shots",
  "drives",
  "picks",
];

export const POPULATION_LABELS: Record<SeasonPopulation, string> = {
  position: "Same position group",
  edition: "Whole edition",
  team: "Same team",
};

export function parseMetricList(raw: string | undefined): string[] {
  return (raw ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter((item, index, all) => item.length > 0 && all.indexOf(item) === index);
}

/** Selected metrics that the family registry actually defines, in request order. */
export function resolveSelectedMetrics(
  family: SeasonFamily,
  raw: string | undefined,
  registry: readonly SeasonMetricView[],
): string[] {
  const known = new Set(registry.map((metric) => metric.column));
  const requested = parseMetricList(raw).filter((column) => known.has(column));
  if (requested.length > 0) return requested;
  return DEFAULT_SEASON_METRICS[family].filter((column) => known.has(column));
}

/**
 * TIP/OTIP counterparts of the selected physical metrics. They are requested with
 * the profile so the split panel ranks inside the same population, not fetched
 * as a second, differently-scoped query.
 */
export function splitCounterparts(
  selected: readonly string[],
  registry: readonly SeasonMetricView[],
): string[] {
  const byColumn = new Map(registry.map((metric) => [metric.column, metric]));
  const extra: string[] = [];
  for (const column of selected) {
    const metric = byColumn.get(column);
    if (!metric || metric.split !== "all" || !metric.base) continue;
    for (const split of ["tip", "otip"]) {
      const counterpart = `${metric.base}_full_${split}`;
      if (byColumn.has(counterpart) && !selected.includes(counterpart) && !extra.includes(counterpart)) {
        extra.push(counterpart);
      }
    }
  }
  return extra;
}

export interface SplitPair {
  readonly base: string;
  readonly label: string;
  readonly unit: string;
  readonly tip: SeasonRankedMetricView | null;
  readonly otip: SeasonRankedMetricView | null;
}

export function splitPairs(
  selected: readonly string[],
  registry: readonly SeasonMetricView[],
  ranked: readonly SeasonRankedMetricView[],
): SplitPair[] {
  const byColumn = new Map(registry.map((metric) => [metric.column, metric]));
  const values = new Map(ranked.map((metric) => [metric.column, metric]));
  const pairs: SplitPair[] = [];
  for (const column of selected) {
    const metric = byColumn.get(column);
    if (!metric || metric.split !== "all" || !metric.base) continue;
    const tip = values.get(`${metric.base}_full_tip`) ?? null;
    const otip = values.get(`${metric.base}_full_otip`) ?? null;
    if (tip === null && otip === null) continue;
    pairs.push({ base: metric.base, label: metric.label, unit: metric.unit, tip, otip });
  }
  return pairs;
}

export interface MetricGroup {
  readonly group: string;
  readonly metrics: readonly SeasonMetricView[];
}

/** Registry metrics grouped in first-appearance order, exposure last. */
export function groupMetrics(metrics: readonly SeasonMetricView[]): MetricGroup[] {
  const groups = new Map<string, SeasonMetricView[]>();
  for (const metric of metrics) {
    const list = groups.get(metric.group) ?? [];
    list.push(metric);
    groups.set(metric.group, list);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => Number(a === "Exposure") - Number(b === "Exposure"))
    .map(([group, list]) => ({ group, metrics: list }));
}

const UNIT_DIGITS: Record<string, number> = {
  m: 0,
  "m/min": 1,
  "km/h": 2,
  s: 2,
  "%": 1,
  min: 1,
  count: 1,
  matches: 0,
};

export function formatSeasonValue(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const digits = UNIT_DIGITS[unit] ?? 2;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function unitSuffix(unit: string): string {
  return unit === "count" || unit === "matches" ? "" : unit;
}

/** Position of a value inside [min, max] as a 0..1 fraction, or null. */
export function rangePosition(
  value: number | null | undefined,
  minimum: number | null | undefined,
  maximum: number | null | undefined,
): number | null {
  if (value === null || value === undefined || minimum === null || minimum === undefined) return null;
  if (maximum === null || maximum === undefined) return null;
  if (maximum === minimum) return 0.5;
  return Math.min(1, Math.max(0, (value - minimum) / (maximum - minimum)));
}

export function ordinalPercentile(percentile: number | null | undefined): string {
  if (percentile === null || percentile === undefined) return "—";
  return `P${Math.round(percentile)}`;
}

export function shortTeamName(name: string): string {
  return name
    .replace(/\s+(Football Club|Football|FC)$/u, "")
    .replace(/^(Football Club)\s+/u, "")
    .trim();
}

export function playerInitials(name: string): string {
  const parts = name.split(/\s+/u).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return `${first}${last}`.toUpperCase();
}

export interface SeasonReportInput {
  readonly profile: SeasonProfileView;
  readonly registry: readonly SeasonMetricView[];
  readonly compare?: SeasonProfileView | null | undefined;
  readonly url: string;
}

/**
 * Reproducible season-profile report (Markdown). It carries every input needed to
 * regenerate the numbers: edition, family artifact + checksum + run, registry
 * version, population rule and the durable URL.
 */
export function buildSeasonReport({ profile, registry, compare, url }: SeasonReportInput): string {
  const byColumn = new Map(registry.map((metric) => [metric.column, metric]));
  const edition: SeasonEditionView = profile.edition;
  const family: SeasonFamilyRef = profile.family;
  const row = profile.row;
  const compareValues = new Map((compare?.metrics ?? []).map((metric) => [metric.column, metric]));
  const lines: string[] = [];
  lines.push(`# Season profile — ${row.player_name}`);
  lines.push("");
  lines.push(
    `${edition.sport_name} · ${edition.competition_name} ${edition.edition_label} · ${row.team_name} · ${row.position_group}`,
  );
  lines.push("");
  lines.push("## Context");
  lines.push(`- Family: ${family.label} (${family.grain_kind}; grain ${family.grain_axes.join(" × ")})`);
  lines.push(`- Included matches in this row: ${row.matches ?? "—"}`);
  lines.push(`- Measurement class: ${edition.measurement_class}`);
  lines.push(`- Inclusion rule: ${edition.inclusion_rule}`);
  lines.push("");
  lines.push("## Comparison denominator");
  lines.push(`- Population: ${profile.population.label}`);
  lines.push(`- Rows: ${profile.population.rows} (${profile.population.unit_of_analysis})`);
  lines.push(`- Percentile: ${profile.percentile_method}`);
  lines.push(`- Rank: ${profile.rank_method}`);
  if (compare) {
    lines.push(
      `- Compared with ${compare.row.player_name} (${compare.row.team_name}, ${compare.row.position_group}) against the same population${compare.population.selected_row_in_population ? "" : " — outside that population"}.`,
    );
  }
  lines.push("");
  lines.push("## Metrics");
  const header = compare
    ? "| Metric | Basis | Value | Rank | Percentile | " + compare.row.player_name + " | Valid n |"
    : "| Metric | Basis | Value | Rank | Percentile | Valid n |";
  lines.push(header);
  lines.push(compare ? "|---|---|---:|---:|---:|---:|---:|" : "|---|---|---:|---:|---:|---:|");
  for (const metric of profile.metrics) {
    const definition = byColumn.get(metric.column);
    const unit = definition?.unit ?? "";
    const value = `${formatSeasonValue(metric.value, unit)} ${unitSuffix(unit)}`.trim();
    const cells = [
      definition?.label ?? metric.column,
      definition?.basis ?? "",
      value,
      metric.rank === null ? "—" : `${metric.rank}/${metric.valid_n}`,
      ordinalPercentile(metric.percentile),
    ];
    if (compare) {
      const other = compareValues.get(metric.column);
      cells.push(`${formatSeasonValue(other?.value, unit)} ${unitSuffix(unit)}`.trim());
    }
    cells.push(String(metric.valid_n));
    lines.push(`| ${cells.join(" | ")} |`);
  }
  lines.push("");
  lines.push("## Provenance");
  lines.push(`- Provider: ${edition.provider} (dataset \`${edition.dataset_id}\`)`);
  lines.push(`- Artifact: \`${family.artifact_id}\` sha256 \`${family.checksum_sha256}\``);
  lines.push(`- Run: \`${family.run_id ?? "—"}\``);
  lines.push(`- Source revision: \`${family.source_revision ?? "—"}\` · file \`${family.source_file_key ?? "—"}\``);
  lines.push(`- Source population rows: ${family.source_population_rows ?? "—"}`);
  lines.push(`- Metric registry: \`${edition.registry_version}\``);
  if (edition.glossary_url) lines.push(`- Provider glossary: ${edition.glossary_url}`);
  lines.push("");
  lines.push("## Rights");
  lines.push(`- ${edition.license.notice}`);
  lines.push("");
  lines.push("## Caveats");
  for (const caveat of profile.caveats) lines.push(`- ${caveat}`);
  lines.push("");
  lines.push(`Reproduce: ${url}`);
  return lines.join("\n");
}
