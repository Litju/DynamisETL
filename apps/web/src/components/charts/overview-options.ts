/**
 * Overview chart options.
 *
 * These plot served Gold values directly: a bar is one row of the mart, and
 * clicking it selects that exact row. Nothing is aggregated, smoothed or
 * normalised, so every mark keeps the method, run and provenance of the value
 * behind it.
 */

import type { EChartsOption } from "echarts";

import type { ChartPalette } from "@/lib/chart-palette";
import { seriesColor } from "@/lib/chart-palette";
import type { MetricSummary, ZoneSeries } from "@/lib/overview-summaries";

/** Entities shown before the chart becomes a wall of labels. */
export const MAX_RANKED_ENTITIES = 18;

function valueFormatter(unit: string) {
  return (value: number): string => {
    if (!Number.isFinite(value)) return "unavailable";
    const magnitude = Math.abs(value);
    const digits = magnitude >= 1000 ? 0 : magnitude >= 100 ? 1 : magnitude >= 1 ? 2 : 3;
    const text = value.toFixed(digits);
    return unit === "1" ? text : `${text} ${unit}`;
  };
}

/**
 * Ranked horizontal bars, one per entity.
 *
 * Horizontal because entity ids are long and a vertical axis reads them
 * without rotation; ranked because the ordering is the analysis.
 */
export function rankedMetricOption(
  summary: MetricSummary,
  palette: ChartPalette,
): EChartsOption {
  const shown = summary.ranked.slice(0, MAX_RANKED_ENTITIES);
  // ECharts stacks a value axis upward, so the order is reversed to put the
  // largest value at the top of the chart.
  const entries = [...shown].reverse();
  const format = valueFormatter(summary.siUnit);

  return {
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      description: `${summary.metricName} for each entity, ranked, in ${summary.siUnit}.`,
    },
    grid: { left: 8, right: 64, top: 8, bottom: 26, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: palette.surface,
      borderColor: palette.border,
      borderWidth: 1,
      textStyle: { color: palette.text, fontSize: 11 },
      formatter: (params: unknown) => {
        const point = params as { name?: string; value?: number };
        return `${point.name ?? ""}<br/>${format(Number(point.value))}`;
      },
    },
    xAxis: {
      type: "value",
      name: summary.siUnit === "1" ? "" : summary.siUnit,
      nameLocation: "end",
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    yAxis: {
      type: "category",
      data: entries.map((entry) => entry.entityId),
      axisLabel: { color: palette.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: palette.border } },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        name: summary.metricName,
        data: entries.map((entry) => entry.value),
        itemStyle: {
          color: seriesColor(palette, summary.measurementClass),
          borderRadius: [0, 2, 2, 0],
        },
        barMaxWidth: 14,
        label: {
          show: true,
          position: "right",
          color: palette.textMuted,
          fontSize: 10,
          formatter: (params: { value?: unknown }) => format(Number(params.value)),
        },
        animation: false,
      },
    ],
  };
}

/** Stacked zone breakdown; one bar per entity, one stack per served zone. */
export function zoneBreakdownOption(
  zones: ZoneSeries,
  palette: ChartPalette,
  maxEntities = MAX_RANKED_ENTITIES,
): EChartsOption {
  const entities = zones.entities.slice(0, maxEntities);
  const shown = [...entities].reverse();
  const indexes = shown.map((entityId) => zones.entities.indexOf(entityId));
  const format = valueFormatter(zones.siUnit);

  return {
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      description: `${zones.label} for each entity, in ${zones.siUnit}.`,
    },
    grid: { left: 8, right: 16, top: 26, bottom: 26, containLabel: true },
    legend: {
      top: 0,
      textStyle: { color: palette.textMuted, fontSize: 10 },
      inactiveColor: palette.axis,
      itemWidth: 12,
      itemHeight: 8,
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: palette.surface,
      borderColor: palette.border,
      borderWidth: 1,
      textStyle: { color: palette.text, fontSize: 11 },
      valueFormatter: (value: unknown) => format(Number(value)),
    },
    xAxis: {
      type: "value",
      name: zones.siUnit === "1" ? "" : zones.siUnit,
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    yAxis: {
      type: "category",
      data: shown,
      axisLabel: { color: palette.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: palette.border } },
      axisTick: { show: false },
    },
    series: zones.zones.map((zone, zoneIndex) => ({
      type: "bar" as const,
      name: zone,
      stack: "zones",
      data: indexes.map((index) => zones.values[zoneIndex]?.[index] ?? null),
      itemStyle: {
        color: palette.series[zoneIndex % palette.series.length] ?? palette.axis,
      },
      barMaxWidth: 14,
      animation: false,
    })),
  };
}
