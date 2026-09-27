import { motion } from "motion/react";
import { useMemo } from "react";

import type { SeasonMetricView, SeasonProfileView, SeasonRankedMetricView } from "@/api/types";
import { cn } from "@/lib/cn";
import {
  formatSeasonValue,
  groupMetrics,
  ordinalPercentile,
  rangePosition,
  splitPairs,
  unitSuffix,
} from "@/lib/season-model";

const MARKER_TRANSITION = { type: "tween", duration: 0.24, ease: [0.2, 0, 0, 1] } as const;

/**
 * Ranked metric rows as instrument range strips.
 *
 * Each strip spans the population's observed minimum → maximum with a median
 * tick; the selected row is a filled circle, a comparison row a hollow diamond.
 * Position encodes value, shape encodes identity, and the exact value, rank and
 * denominator are always printed — colour alone never carries meaning.
 */
export function MetricProfile({
  registry,
  ranked,
  compare,
  focus,
  onFocus,
}: {
  registry: readonly SeasonMetricView[];
  ranked: readonly SeasonRankedMetricView[];
  compare: SeasonProfileView | null;
  focus: string | null;
  onFocus: (column: string) => void;
}) {
  const byColumn = useMemo(() => new Map(registry.map((metric) => [metric.column, metric])), [registry]);
  const compareByColumn = useMemo(
    () => new Map((compare?.metrics ?? []).map((metric) => [metric.column, metric])),
    [compare],
  );
  const groups = useMemo(
    () =>
      groupMetrics(
        ranked
          .map((metric) => byColumn.get(metric.column))
          .filter((metric): metric is SeasonMetricView => metric !== undefined),
      ),
    [byColumn, ranked],
  );
  const rankedByColumn = useMemo(() => new Map(ranked.map((metric) => [metric.column, metric])), [ranked]);

  return (
    <div className="season-strips flex flex-col gap-4">
      {compare ? (
        <p className="flex flex-wrap items-center gap-3 text-[11px] text-text-muted">
          <LegendMark kind="selected" /> Selected
          <LegendMark kind="compare" /> {compare.row.player_name}
          {!compare.population.selected_row_in_population ? (
            <span className="text-quality-warning">
              ◆ ranked against this population but not a member of it ({compare.row.position_group})
            </span>
          ) : null}
        </p>
      ) : null}
      {groups.map((group) => (
        <div key={group.group} role="group" aria-label={group.group}>
          <p className="t-label mb-1">{group.group}</p>
          <ul className="flex flex-col">
            {group.metrics.map((metric) => {
              const value = rankedByColumn.get(metric.column);
              if (!value) return null;
              return (
                <li key={metric.column}>
                  <StripRow
                    metric={metric}
                    value={value}
                    compare={compareByColumn.get(metric.column) ?? null}
                    active={focus === metric.column}
                    onFocus={() => onFocus(metric.column)}
                  />
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function LegendMark({ kind }: { kind: "selected" | "compare" }) {
  return kind === "selected" ? (
    <span aria-hidden="true" className="inline-block size-2.5 rounded-full bg-playhead" />
  ) : (
    <span aria-hidden="true" className="inline-block size-2.5 rotate-45 border-2 border-quality-warning" />
  );
}

function StripRow({
  metric,
  value,
  compare,
  active,
  onFocus,
}: {
  metric: SeasonMetricView;
  value: SeasonRankedMetricView;
  compare: SeasonRankedMetricView | null;
  active: boolean;
  onFocus: () => void;
}) {
  const position = rangePosition(value.value, value.population_minimum, value.population_maximum);
  const median = rangePosition(value.population_median, value.population_minimum, value.population_maximum);
  const comparePosition = compare
    ? rangePosition(compare.value, value.population_minimum, value.population_maximum)
    : null;
  const suffix = unitSuffix(metric.unit);
  const rankText = value.rank === null ? "no rank" : `${value.rank} / ${value.valid_n}`;
  return (
    <button
      type="button"
      onClick={onFocus}
      aria-pressed={active}
      aria-label={`${metric.label}: ${formatSeasonValue(value.value, metric.unit)} ${suffix}, rank ${rankText}, ${ordinalPercentile(value.percentile)}`}
      className={cn(
        "season-strip group grid w-full items-center gap-x-4 rounded-control px-2 py-1.5 text-left transition-colors duration-quick",
        active ? "bg-surface-2" : "hover:bg-surface-1",
      )}
    >
      <span className="min-w-0">
        <span className={cn("block truncate text-[12px]", active ? "text-text-primary" : "text-text-secondary")}>
          {metric.label}
        </span>
        <span className="season-strip-basis block truncate text-[10px] text-text-muted">{metric.basis}</span>
      </span>
      <span className="text-right">
        <span className="mono text-[13px] text-text-primary">{formatSeasonValue(value.value, metric.unit)}</span>
        {suffix ? <span className="ml-1 text-[10px] text-text-muted">{suffix}</span> : null}
        {compare ? (
          <span className="mono block text-[10px] text-quality-warning">
            ◆ {formatSeasonValue(compare.value, metric.unit)}
          </span>
        ) : null}
      </span>
      <span className="season-strip-track relative h-5" aria-hidden="true">
        <span className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border-strong" />
        <span className="absolute left-0 top-1/2 h-2 w-px -translate-y-1/2 bg-border-strong" />
        <span className="absolute right-0 top-1/2 h-2 w-px -translate-y-1/2 bg-border-strong" />
        {median !== null ? (
          <span className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-chart-reference" style={{ left: `${median * 100}%` }} />
        ) : null}
        {position !== null ? (
          <motion.span
            className="absolute top-1/2 h-px bg-accent/70"
            style={{ left: 0, y: "-50%" }}
            initial={false}
            animate={{ width: `${position * 100}%` }}
            transition={MARKER_TRANSITION}
          />
        ) : null}
        {comparePosition !== null ? (
          <motion.span
            className="absolute top-1/2 size-2.5 border-2 border-quality-warning bg-surface-0"
            style={{ x: "-50%", y: "-50%", rotate: 45 }}
            initial={false}
            animate={{ left: `${comparePosition * 100}%` }}
            transition={MARKER_TRANSITION}
          />
        ) : null}
        {position !== null ? (
          <motion.span
            className="season-strip-marker absolute top-1/2 size-3 rounded-full border-2 border-surface-0 bg-playhead"
            style={{ x: "-50%", y: "-50%" }}
            initial={false}
            animate={{ left: `${position * 100}%` }}
            transition={MARKER_TRANSITION}
          />
        ) : null}
      </span>
      <span className="season-strip-rank mono text-right text-[11px] text-text-muted">{rankText}</span>
      <span className="season-strip-pct mono text-right text-[12px] text-text-secondary">{ordinalPercentile(value.percentile)}</span>
    </button>
  );
}

/** Paired TIP/OTIP bars for the selected physical metrics, on a shared axis per pair. */
export function SplitComparison({
  registry,
  selected,
  ranked,
}: {
  registry: readonly SeasonMetricView[];
  selected: readonly string[];
  ranked: readonly SeasonRankedMetricView[];
}) {
  const pairs = splitPairs(selected, registry, ranked);
  if (pairs.length === 0) {
    return (
      <p className="t-body">
        None of the selected metrics has a TIP/OTIP split. Add a full-match physical metric to compare phases.
      </p>
    );
  }
  return (
    <ul className="grid gap-x-8 gap-y-3 [grid-template-columns:repeat(auto-fill,minmax(15rem,1fr))]">
      {pairs.map((pair) => {
        const scale = Math.max(pair.tip?.population_maximum ?? 0, pair.otip?.population_maximum ?? 0) || 1;
        return (
          <li key={pair.base} className="flex flex-col gap-1">
            <span className="text-[12px] text-text-secondary">{pair.label}</span>
            {(
              [
                ["TIP", pair.tip, "bg-accent"],
                ["OTIP", pair.otip, "bg-text-muted"],
              ] as const
            ).map(([label, metric, tone]) => (
              <div key={label} className="grid grid-cols-[2.25rem_minmax(3rem,1fr)_auto_2.25rem] items-center gap-2">
                <span className="text-[10px] font-medium tracking-[0.06em] text-text-muted">{label}</span>
                <span className="relative h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
                  <motion.span
                    className={cn("absolute inset-y-0 left-0 rounded-full", tone)}
                    initial={false}
                    animate={{ width: `${Math.max(0, Math.min(1, (metric?.value ?? 0) / scale)) * 100}%` }}
                    transition={MARKER_TRANSITION}
                  />
                </span>
                <span className="mono whitespace-nowrap text-right text-[11px] text-text-primary">
                  {formatSeasonValue(metric?.value, pair.unit)} <span className="text-text-muted">{unitSuffix(pair.unit)}</span>
                </span>
                <span className="mono text-right text-[10px] text-text-muted">{ordinalPercentile(metric?.percentile)}</span>
              </div>
            ))}
          </li>
        );
      })}
    </ul>
  );
}
