import { useMemo } from "react";

import type { SeasonMetricView, SeasonRankedMetricView, SeasonRowView } from "@/api/types";
import { EChart } from "@/components/charts/EChart";
import { LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { distributionStripOption, percentileRadarOption } from "@/components/season/season-options";
import { readPalette } from "@/lib/chart-palette";
import { cn } from "@/lib/cn";
import { formatSeasonValue, unitSuffix } from "@/lib/season-model";

function keyOf(row: Pick<SeasonRowView, "subject_id" | "team_id" | "position_group">): string {
  return `${row.subject_id}|${row.team_id}|${row.position_group}`;
}

/**
 * Focused-metric distribution plus a percentile radar of the selected panel.
 * Both read the same population rows the profile was ranked against.
 */
export function SeasonFocusCharts({
  registry,
  focus,
  populationRows,
  populationLabel,
  selected,
  compare,
  radarMetrics,
  compareRanked = null,
  onFocus,
}: {
  registry: readonly SeasonMetricView[];
  focus: string | null;
  populationRows: readonly SeasonRowView[] | null;
  populationLabel: string;
  selected: SeasonRowView | null;
  compare: SeasonRowView | null;
  radarMetrics: readonly SeasonRankedMetricView[];
  compareRanked?: readonly SeasonRankedMetricView[] | null;
  onFocus: (column: string) => void;
}) {
  const palette = useMemo(() => readPalette(), []);
  const metric = registry.find((item) => item.column === focus) ?? null;
  const byColumn = useMemo(() => new Map(registry.map((item) => [item.column, item])), [registry]);

  const strip = useMemo(() => {
    if (!metric || !populationRows) return null;
    const points = populationRows
      .map((row) => ({
        value: row.values[metric.column],
        label: `${row.player_name} · ${row.position_group}`,
        key: keyOf(row),
      }))
      .filter((point): point is { value: number; label: string; key: string } =>
        typeof point.value === "number" && Number.isFinite(point.value),
      );
    // A selected/compared row outside the population is drawn but never counted.
    for (const extra of [selected, compare]) {
      if (!extra) continue;
      const value = extra.values[metric.column];
      if (typeof value === "number" && !points.some((point) => point.key === keyOf(extra))) {
        points.push({ value, label: `${extra.player_name} · ${extra.position_group}`, key: keyOf(extra) });
      }
    }
    const sorted = populationRows
      .map((row) => row.values[metric.column])
      .filter((value): value is number => typeof value === "number")
      .sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    const median =
      sorted.length === 0
        ? null
        : sorted.length % 2
          ? sorted[middle]!
          : (sorted[middle - 1]! + sorted[middle]!) / 2;
    return {
      option: distributionStripOption({
        points,
        selectedKey: selected ? keyOf(selected) : null,
        compareKey: compare ? keyOf(compare) : null,
        unit: metric.unit,
        metricLabel: metric.label,
        populationLabel,
        median,
        palette,
      }),
      valid: sorted.length,
    };
  }, [compare, metric, palette, populationLabel, populationRows, selected]);

  const radar = useMemo(() => {
    const axes = radarMetrics
      .filter((item) => item.percentile !== null && !byColumn.get(item.column)?.exposure)
      .slice(0, 12)
      .map((item) => ({
        label: byColumn.get(item.column)?.label ?? item.column,
        selected: item.percentile,
        compare: compareRanked?.find((other) => other.column === item.column)?.percentile ?? null,
      }));
    if (axes.length < 3 || !selected) return null;
    return percentileRadarOption({
      axes,
      selectedLabel: selected.player_name,
      compareLabel: compare?.player_name ?? null,
      palette,
    });
  }, [byColumn, compare, compareRanked, palette, radarMetrics, selected]);

  return (
    <div className={cn("season-charts grid gap-6", radar ? "season-charts--with-radar" : "")}>
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="t-section">Distribution</h3>
          {metric ? (
            <span className="t-label truncate">
              {metric.label} · {metric.basis} · {strip?.valid ?? "…"} valid rows of {populationLabel}
            </span>
          ) : null}
        </div>
        {!metric ? (
          <StatePanel state="empty" title="Select a metric to see its distribution." className="min-h-40" />
        ) : !strip ? (
          <LoadingPanel label="Loading population values" />
        ) : (
          <div className="h-48">
            <EChart
              option={strip.option}
              ariaLabel={`${metric.label} distribution across ${populationLabel}`}
              className="min-h-0"
            />
          </div>
        )}
        {metric && selected ? (
          <p className="mt-1 text-[11px] text-text-muted">
            <span className="mr-1 inline-block size-2 rounded-full bg-playhead align-middle" aria-hidden="true" />
            {selected.player_name}:{" "}
            <span className="mono text-text-secondary">
              {formatSeasonValue(selected.values[metric.column], metric.unit)} {unitSuffix(metric.unit)}
            </span>
            {compare ? (
              <>
                <span className="mx-2 inline-block size-2 rotate-45 border border-quality-warning align-middle" aria-hidden="true" />
                {compare.player_name}:{" "}
                <span className="mono text-text-secondary">
                  {formatSeasonValue(compare.values[metric.column], metric.unit)} {unitSuffix(metric.unit)}
                </span>
              </>
            ) : null}
          </p>
        ) : null}
        {!selected ? (
          <MetricChips registry={registry} focus={focus} onFocus={onFocus} />
        ) : null}
      </div>
      {radar ? (
        <div className="min-w-0">
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <h3 className="t-section">Percentile shape</h3>
            <span className="t-label">0–100 within the stated population</span>
          </div>
          <div className="h-60">
            <EChart option={radar} ariaLabel="Percentile radar of the selected metrics" className="min-h-0" />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MetricChips({
  registry,
  focus,
  onFocus,
}: {
  registry: readonly SeasonMetricView[];
  focus: string | null;
  onFocus: (column: string) => void;
}) {
  const visible = registry.filter((metric) => !metric.exposure && (metric.split === null || metric.split === "all" || metric.split === "runs"));
  return (
    <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Distribution metric">
      {visible.slice(0, 24).map((metric) => (
        <button
          key={metric.column}
          type="button"
          aria-pressed={metric.column === focus}
          onClick={() => onFocus(metric.column)}
          className={cn(
            "rounded-full border px-2 py-0.5 text-[11px] transition-colors duration-quick",
            metric.column === focus
              ? "border-accent text-text-primary"
              : "border-border-subtle text-text-muted hover:border-border-strong hover:text-text-secondary",
          )}
        >
          {metric.label}
        </button>
      ))}
    </div>
  );
}
