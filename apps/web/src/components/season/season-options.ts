/**
 * SeasonLab chart options.
 *
 * Both views are descriptive and name their population. The distribution is a
 * one-dimensional strip of every population row (jittered only on the empty
 * axis, never on the value axis) with the selected and compared rows marked by
 * shape as well as colour. The radar plots percentiles, whose domain is fixed at
 * 0–100 by definition, so its geometry never depends on an arbitrary scale.
 */

import type { EChartsOption } from "echarts";

import type { ChartPalette } from "@/lib/chart-palette";
import { formatSeasonValue, unitSuffix } from "@/lib/season-model";

export interface StripPoint {
  readonly value: number;
  readonly label: string;
  readonly key: string;
}

/** Deterministic jitter in [-0.36, 0.36] from a string key; stable across renders. */
export function stableJitter(key: string): number {
  let hash = 2166136261;
  for (let index = 0; index < key.length; index += 1) {
    hash ^= key.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (((hash >>> 0) % 1000) / 1000 - 0.5) * 0.72;
}

export function distributionStripOption({
  points,
  selectedKey,
  compareKey,
  unit,
  metricLabel,
  populationLabel,
  median,
  palette,
}: {
  points: readonly StripPoint[];
  selectedKey: string | null;
  compareKey: string | null;
  unit: string;
  metricLabel: string;
  populationLabel: string;
  median: number | null;
  palette: ChartPalette;
}): EChartsOption {
  const suffix = unitSuffix(unit);
  const background = points
    .filter((point) => point.key !== selectedKey && point.key !== compareKey)
    .map((point) => ({
      value: [point.value, stableJitter(point.key)],
      name: point.label,
    }));
  const selected = points.find((point) => point.key === selectedKey) ?? null;
  const compare = points.find((point) => point.key === compareKey) ?? null;
  const values = points.map((point) => point.value);
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 1;
  const pad = (maximum - minimum) * 0.04 || 1;

  return {
    animation: true,
    animationDuration: 260,
    animationEasing: "cubicOut",
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      description: `${metricLabel}: each dot is one row of ${populationLabel}.`,
    },
    grid: { left: 12, right: 16, top: 18, bottom: 30, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: palette.surface,
      borderColor: palette.border,
      textStyle: { color: palette.text, fontSize: 11, fontFamily: "Inter Variable, Inter, sans-serif" },
      formatter: (params: unknown) => {
        const item = params as { name?: string; value?: [number, number] };
        const value = Array.isArray(item.value) ? item.value[0] : Number.NaN;
        return `${item.name ?? ""}<br/><b>${formatSeasonValue(value, unit)}</b> ${suffix}`;
      },
    },
    xAxis: {
      type: "value",
      min: minimum - pad,
      max: maximum + pad,
      name: suffix,
      nameLocation: "end",
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLine: { lineStyle: { color: palette.border } },
      axisTick: { show: false },
      axisLabel: {
        color: palette.axis,
        fontSize: 10,
        fontFamily: "JetBrains Mono Variable, JetBrains Mono, monospace",
        formatter: (value: number) => formatSeasonValue(value, unit),
      },
      splitLine: { lineStyle: { color: palette.grid, type: [2, 3] } },
    },
    yAxis: { type: "value", min: -0.6, max: 0.6, show: false },
    series: [
      {
        name: "Population",
        type: "scatter",
        symbolSize: 6,
        itemStyle: { color: palette.textMuted, opacity: 0.42 },
        emphasis: { itemStyle: { opacity: 0.9, color: palette.text } },
        data: background,
        ...(median === null
          ? {}
          : {
              markLine: {
                silent: true,
                symbol: "none",
                lineStyle: { color: palette.reference, type: "dashed", width: 1 },
                label: {
                  formatter: "median",
                  color: palette.textMuted,
                  fontSize: 10,
                  position: "insideEndTop",
                },
                data: [{ xAxis: median }],
              },
            }),
      },
      ...(compare
        ? [
            {
              name: "Compared",
              type: "scatter" as const,
              symbol: "diamond",
              symbolSize: 13,
              z: 4,
              itemStyle: {
                color: "transparent",
                borderColor: palette.warning,
                borderWidth: 2,
              },
              data: [{ value: [compare.value, 0], name: compare.label }],
            },
          ]
        : []),
      ...(selected
        ? [
            {
              name: "Selected",
              type: "scatter" as const,
              symbol: "circle",
              symbolSize: 13,
              z: 5,
              itemStyle: {
                color: palette.playhead,
                borderColor: palette.surface,
                borderWidth: 2,
                shadowBlur: 10,
                shadowColor: palette.playhead,
              },
              data: [{ value: [selected.value, 0], name: selected.label }],
            },
          ]
        : []),
    ],
  };
}

export interface RadarAxis {
  readonly label: string;
  readonly selected: number | null;
  readonly compare: number | null;
}

export function percentileRadarOption({
  axes,
  selectedLabel,
  compareLabel,
  palette,
}: {
  axes: readonly RadarAxis[];
  selectedLabel: string;
  compareLabel: string | null;
  palette: ChartPalette;
}): EChartsOption {
  const series: Array<{ name: string; value: number[]; symbol: string; lineStyle: object; areaStyle: object; itemStyle: object }> = [
    {
      name: selectedLabel,
      value: axes.map((axis) => axis.selected ?? 0),
      symbol: "circle",
      lineStyle: { color: palette.playhead, width: 1.5 },
      areaStyle: { color: palette.playhead, opacity: 0.16 },
      itemStyle: { color: palette.playhead },
    },
  ];
  if (compareLabel) {
    series.push({
      name: compareLabel,
      value: axes.map((axis) => axis.compare ?? 0),
      symbol: "diamond",
      lineStyle: { color: palette.warning, width: 1.25, type: "dashed" },
      areaStyle: { color: palette.warning, opacity: 0.06 },
      itemStyle: { color: palette.warning },
    });
  }
  return {
    animation: true,
    animationDuration: 320,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      description: "Percentile within the stated population for each selected metric (0–100).",
    },
    tooltip: {
      trigger: "item",
      backgroundColor: palette.surface,
      borderColor: palette.border,
      textStyle: { color: palette.text, fontSize: 11 },
    },
    radar: {
      indicator: axes.map((axis) => ({ name: axis.label, max: 100, min: 0 })),
      radius: "60%",
      center: ["50%", "54%"],
      splitNumber: 4,
      shape: "polygon",
      axisName: {
        color: palette.textMuted,
        fontSize: 10,
        formatter: (name?: string) =>
          name && name.length > 18 ? name.replace(" → ", " →\n") : (name ?? ""),
      },
      splitLine: { lineStyle: { color: palette.grid } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: palette.grid } },
    },
    series: [{ type: "radar", data: series, emphasis: { lineStyle: { width: 2 } } }],
  };
}
