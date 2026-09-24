/**
 * Session overview summaries.
 *
 * Every summary here is a *selection or arrangement of served values*, never a
 * new scientific quantity: a ranking orders rows the Gold mart already
 * published, a zone breakdown places three published metrics side by side, and
 * a headline states which served row holds the largest value. Nothing is
 * summed, averaged, normalised or otherwise recomputed in the browser, because
 * a value the pipeline did not produce has no method, no run and no provenance
 * to show next to it.
 */

import type { MetricValue } from "@/api/types";

/**
 * Metrics a reader of each domain looks at first, in preference order. A
 * session opens on the first of these its Gold rows actually contain.
 */
const HEADLINE_PREFERENCE: readonly string[] = [
  "locomotor.distance_total",
  "cmj.jump_height_jhwd",
  "gymaware_mean_power",
  "gymaware_mean_force",
  "locomotor.max_speed",
];

/** Zone family that forms a stacked breakdown when every member is served. */
const ZONE_FAMILY = {
  metricPrefix: "locomotor.distance_zone.",
  order: ["low", "medium", "high"] as const,
  label: "Distance by speed zone",
};

export interface RankedEntry {
  /** Entity the value belongs to: player, subject or trial. */
  readonly entityId: string;
  readonly value: number;
  /** The served row, so a selection can carry its exact provenance. */
  readonly derivedMetricId: string;
  readonly subjectId: string | null;
}

export interface MetricSummary {
  readonly metricId: string;
  readonly metricName: string;
  readonly siUnit: string;
  readonly measurementClass: string;
  /** Descending by value; ties broken by entity id for a stable order. */
  readonly ranked: readonly RankedEntry[];
}

export interface ZoneSeries {
  readonly label: string;
  readonly siUnit: string;
  readonly measurementClass: string;
  readonly zones: readonly string[];
  /** Entity ids in the same order as `values`. */
  readonly entities: readonly string[];
  /** `values[zoneIndex][entityIndex]`; null where that zone was not served. */
  readonly values: ReadonlyArray<ReadonlyArray<number | null>>;
}

/** Identity fields a served metric can be grouped by, most specific first. */
const ENTITY_FIELDS = ["entity_id", "subject_id", "trial_id"] as const;

/** The entity a served metric belongs to, preferring the most specific id. */
export function entityKeyOf(metric: MetricValue): string | null {
  return metric.entity_id ?? metric.subject_id ?? metric.trial_id ?? null;
}

/**
 * The identity field that actually distinguishes the rows of a metric.
 *
 * A locomotor metric varies by player, so `subject_id` separates its rows. A
 * CMJ metric is eight trials of one participant, so `subject_id` is the same
 * value eight times and only `trial_id` tells the rows apart. Ranking on a
 * constant field would draw eight identically labelled bars, so the
 * discriminating field is chosen from the rows themselves.
 */
export function discriminatingField(
  rows: readonly MetricValue[],
): (typeof ENTITY_FIELDS)[number] {
  let best: (typeof ENTITY_FIELDS)[number] = "entity_id";
  let bestCount = 0;
  for (const field of ENTITY_FIELDS) {
    const values = new Set<string>();
    for (const row of rows) {
      const value = row[field];
      if (typeof value === "string" && value.length > 0) values.add(value);
    }
    if (values.size > bestCount) {
      best = field;
      bestCount = values.size;
    }
  }
  return best;
}

function compareEntity(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

/**
 * Choose the metric a session leads with.
 *
 * Preference first, then the metric with the most served values, so a source
 * outside the known vocabulary still opens on its broadest measurement rather
 * than on nothing. Ties break alphabetically to keep the choice deterministic.
 */
export function headlineMetricId(rows: readonly MetricValue[]): string | null {
  const present = new Set(rows.map((row) => row.metric_id));
  for (const candidate of HEADLINE_PREFERENCE) {
    if (present.has(candidate)) return candidate;
  }
  const counts = new Map<string, number>();
  for (const row of rows) {
    if (row.value_num === null) continue;
    counts.set(row.metric_id, (counts.get(row.metric_id) ?? 0) + 1);
  }
  let best: { id: string; count: number } | null = null;
  for (const [id, count] of counts) {
    if (best === null || count > best.count || (count === best.count && id < best.id)) {
      best = { id, count };
    }
  }
  return best?.id ?? null;
}

/** Rank the served values of one metric by entity, descending. */
export function rankMetric(
  rows: readonly MetricValue[],
  metricId: string,
): MetricSummary | null {
  const matching = rows.filter(
    (row) => row.metric_id === metricId && row.value_num !== null,
  );
  if (matching.length === 0) return null;
  const first = matching[0]!;

  const field = discriminatingField(matching);
  const ranked: RankedEntry[] = [];
  for (const row of matching) {
    const entityId = row[field] ?? entityKeyOf(row);
    if (entityId === null) continue;
    ranked.push({
      entityId,
      value: row.value_num as number,
      derivedMetricId: row.derived_metric_id,
      subjectId: row.subject_id,
    });
  }
  if (ranked.length === 0) return null;
  ranked.sort((left, right) =>
    right.value !== left.value
      ? right.value - left.value
      : compareEntity(left.entityId, right.entityId),
  );

  return {
    metricId,
    metricName: first.metric_name ?? metricId,
    siUnit: first.si_unit,
    measurementClass: first.measurement_class,
    ranked,
  };
}

/**
 * Stacked zone breakdown, when every member of the family is served.
 *
 * Entities are ordered by their total across the zones so the chart reads as a
 * ranking; that ordering is a presentation choice over served values and does
 * not introduce a new quantity — no total is ever displayed as a value.
 */
export function zoneBreakdown(rows: readonly MetricValue[]): ZoneSeries | null {
  const field = discriminatingField(
    rows.filter((row) => row.metric_id.startsWith(ZONE_FAMILY.metricPrefix)),
  );
  const byZone = new Map<string, Map<string, number>>();
  let siUnit = "";
  let measurementClass = "";
  for (const zone of ZONE_FAMILY.order) {
    const metricId = `${ZONE_FAMILY.metricPrefix}${zone}`;
    const values = new Map<string, number>();
    for (const row of rows) {
      if (row.metric_id !== metricId || row.value_num === null) continue;
      const entityId = row[field] ?? entityKeyOf(row);
      if (entityId === null) continue;
      values.set(entityId, row.value_num);
      siUnit = row.si_unit;
      measurementClass = row.measurement_class;
    }
    if (values.size === 0) return null;
    byZone.set(zone, values);
  }

  const entities = new Set<string>();
  for (const values of byZone.values()) {
    for (const entityId of values.keys()) entities.add(entityId);
  }
  const ordered = [...entities].sort((left, right) => {
    const total = (entityId: string) =>
      ZONE_FAMILY.order.reduce(
        (sum, zone) => sum + (byZone.get(zone)?.get(entityId) ?? 0),
        0,
      );
    const difference = total(right) - total(left);
    return difference !== 0 ? difference : compareEntity(left, right);
  });

  return {
    label: ZONE_FAMILY.label,
    siUnit,
    measurementClass,
    zones: [...ZONE_FAMILY.order],
    entities: ordered,
    values: ZONE_FAMILY.order.map((zone) =>
      ordered.map((entityId) => byZone.get(zone)?.get(entityId) ?? null),
    ),
  };
}

export interface HeadlineFact {
  readonly label: string;
  readonly value: string;
  readonly detail: string;
  readonly derivedMetricId: string;
  readonly subjectId: string | null;
  readonly measurementClass: string;
}

/**
 * The largest served value of a metric, attributed to the row that holds it.
 *
 * This is a selection, not a statistic: the number shown is exactly one Gold
 * row, so it keeps a method, a run and a provenance chain the reader can open.
 */
export function leadingFact(
  summary: MetricSummary | null,
  format: (value: number, unit: string) => string,
  labelFor?: (entityId: string) => string | undefined,
): HeadlineFact | null {
  const top = summary?.ranked[0];
  if (!summary || !top) return null;
  const name = labelFor?.(top.entityId);
  return {
    label: `Highest ${summary.metricName.toLowerCase()}`,
    value: format(top.value, summary.siUnit),
    detail: `${name ? `${name} · ${top.entityId}` : top.entityId} · highest of ${summary.ranked.length} served values`,
    derivedMetricId: top.derivedMetricId,
    subjectId: top.subjectId,
    measurementClass: summary.measurementClass,
  };
}
