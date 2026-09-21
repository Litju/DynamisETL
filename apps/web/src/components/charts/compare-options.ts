/**
 * Comparison chart options.
 *
 * Three views, each valid only for the semantics it is offered under: a
 * distribution comparison for unpaired groups, a paired scatter against the
 * identity line, and a difference-versus-mean view. Reference geometry (the
 * identity line, the mean-difference line, the spread limits) is drawn in a
 * subdued style so it never reads as data.
 */

import type { EChartsOption } from "echarts";

import type { ChartPalette } from "@/lib/chart-palette";
import { seriesColor } from "@/lib/chart-palette";
import type {
  DifferenceSummary,
  FiveNumber,
  GroupedValues,
  MetricPair,
} from "@/lib/compare-model";
import { fiveNumber } from "@/lib/compare-model";

/** Colour for a paired observation mark; a pairing is always pipeline-derived. */
function pairColor(palette: ChartPalette): string {
  return seriesColor(palette, "PIPELINE_DERIVED");
}

/**
 * Axis tick text.
 *
 * An explicit axis bound is a raw float, and ECharts prints it verbatim:
 * a jump-height axis ended up labelled `0.7970698587402452`. Ticks carry the
 * magnitude, not the full precision; the exact value stays in the tooltip and
 * the evidence table.
 */
function axisTick(value: number): string {
  if (!Number.isFinite(value)) return "";
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(1);
  if (magnitude >= 1) return value.toFixed(2);
  if (magnitude >= 0.01) return value.toFixed(3);
  // A difference axis can sit near zero — jump-height residuals here are
  // around 1e-4 m. Fixed decimals would print every tick as "-0.000", so
  // small magnitudes keep significant digits instead.
  return Number(value.toPrecision(2)).toString();
}

function format(unit: string) {
  return (value: number): string => {
    if (!Number.isFinite(value)) return "unavailable";
    const magnitude = Math.abs(value);
    const digits = magnitude >= 1000 ? 0 : magnitude >= 100 ? 1 : magnitude >= 1 ? 2 : 4;
    const text = value.toFixed(digits);
    return unit === "1" ? text : `${text} ${unit}`;
  };
}

/** Box plot of served values per group; unpaired by construction. */
export function distributionOption(
  groups: readonly GroupedValues[],
  unit: string,
  measurementClass: string,
  palette: ChartPalette,
): EChartsOption {
  const summaries = groups
    .map((group) => ({ group, summary: fiveNumber(group.values) }))
    .filter((entry): entry is { group: GroupedValues; summary: FiveNumber } =>
      entry.summary !== null,
    );
  const show = format(unit);

  return {
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      description: `Distribution of served values for each group, in ${unit}.`,
    },
    grid: { left: 8, right: 16, top: 16, bottom: 30, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: palette.surface,
      borderColor: palette.border,
      borderWidth: 1,
      textStyle: { color: palette.text, fontSize: 11 },
      formatter: (params: unknown) => {
        const point = params as { dataIndex?: number };
        const entry = summaries[point.dataIndex ?? -1];
        if (!entry) return "";
        const { summary } = entry;
        return [
          entry.group.groupId,
          `n = ${summary.count}`,
          `max ${show(summary.max)}`,
          `q3 ${show(summary.q3)}`,
          `median ${show(summary.median)}`,
          `q1 ${show(summary.q1)}`,
          `min ${show(summary.min)}`,
        ].join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      data: summaries.map((entry) => entry.group.groupId),
      axisLabel: { color: palette.axis, fontSize: 10, interval: 0, hideOverlap: true },
      axisLine: { lineStyle: { color: palette.border } },
    },
    yAxis: {
      type: "value",
      scale: true,
      name: unit === "1" ? "" : unit,
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10, formatter: axisTick },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    series: [
      {
        type: "boxplot",
        // ECharts boxplot order: [min, q1, median, q3, max].
        data: summaries.map((entry) => [
          entry.summary.min,
          entry.summary.q1,
          entry.summary.median,
          entry.summary.q3,
          entry.summary.max,
        ]),
        itemStyle: {
          borderColor: seriesColor(palette, measurementClass),
          color: "transparent",
          borderWidth: 1.4,
        },
        boxWidth: [10, 40],
        animation: false,
      },
    ],
  };
}

/** Paired scatter with the identity line; only for a genuine pairing. */
export function pairedScatterOption(
  pairs: readonly MetricPair[],
  labels: { readonly a: string; readonly b: string; readonly unit: string },
  palette: ChartPalette,
): EChartsOption {
  const values = pairs.flatMap((pair) => [pair.a, pair.b]).filter(Number.isFinite);
  const min = values.length > 0 ? Math.min(...values) : 0;
  const max = values.length > 0 ? Math.max(...values) : 1;
  const pad = (max - min) * 0.06 || 1;
  const low = min - pad;
  const high = max + pad;
  const show = format(labels.unit);

  return {
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      description: `Each paired observation plotted as ${labels.a} against ${labels.b}, with the identity line.`,
    },
    grid: { left: 8, right: 20, top: 16, bottom: 34, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: palette.surface,
      borderColor: palette.border,
      borderWidth: 1,
      textStyle: { color: palette.text, fontSize: 11 },
      formatter: (params: unknown) => {
        const point = params as { dataIndex?: number };
        const pair = pairs[point.dataIndex ?? -1];
        if (!pair) return "";
        return `${pair.label}<br/>${labels.a}: ${show(pair.a)}<br/>${labels.b}: ${show(pair.b)}`;
      },
    },
    xAxis: {
      type: "value",
      min: low,
      max: high,
      name: `${labels.a}${labels.unit === "1" ? "" : ` [${labels.unit}]`}`,
      nameLocation: "middle",
      nameGap: 24,
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10, formatter: axisTick },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    yAxis: {
      type: "value",
      min: low,
      max: high,
      name: `${labels.b}${labels.unit === "1" ? "" : ` [${labels.unit}]`}`,
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10, formatter: axisTick },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    series: [
      {
        // Identity, not a fit: where the two metrics would agree exactly.
        type: "line",
        name: "identity",
        data: [
          [low, low],
          [high, high],
        ],
        showSymbol: false,
        lineStyle: { color: palette.reference, width: 1, type: "dashed" },
        silent: true,
        animation: false,
      },
      {
        type: "scatter",
        name: "paired observations",
        data: pairs.map((pair) => [pair.a, pair.b]),
        symbolSize: 7,
        itemStyle: { color: pairColor(palette) },
        animation: false,
      },
    ],
  };
}

/** Difference against mean, with the descriptive spread of the differences. */
export function differenceOption(
  summary: DifferenceSummary,
  labels: { readonly a: string; readonly b: string; readonly unit: string },
  palette: ChartPalette,
): EChartsOption {
  const show = format(labels.unit);
  const reference = (value: number, text: string) => ({
    yAxis: value,
    label: {
      show: true,
      formatter: `${text} ${show(value)}`,
      color: palette.textMuted,
      fontSize: 9,
      position: "insideEndTop" as const,
    },
  });

  return {
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      description: `Difference between ${labels.b} and ${labels.a} against their mean, for each paired observation.`,
    },
    grid: { left: 8, right: 20, top: 16, bottom: 34, containLabel: true },
    tooltip: {
      trigger: "item",
      backgroundColor: palette.surface,
      borderColor: palette.border,
      borderWidth: 1,
      textStyle: { color: palette.text, fontSize: 11 },
      formatter: (params: unknown) => {
        const point = params as { value?: [number, number] };
        if (!Array.isArray(point.value)) return "";
        return `mean ${show(point.value[0])}<br/>difference ${show(point.value[1])}`;
      },
    },
    xAxis: {
      type: "value",
      scale: true,
      name: `mean of the pair${labels.unit === "1" ? "" : ` [${labels.unit}]`}`,
      nameLocation: "middle",
      nameGap: 24,
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10, formatter: axisTick },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    yAxis: {
      type: "value",
      scale: true,
      name: `${labels.b} − ${labels.a}${labels.unit === "1" ? "" : ` [${labels.unit}]`}`,
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10, formatter: axisTick },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    series: [
      {
        type: "scatter",
        name: "paired differences",
        data: summary.points.map((point) => [point[0], point[1]]),
        symbolSize: 7,
        itemStyle: { color: pairColor(palette) },
        animation: false,
        markLine: {
          silent: true,
          symbol: "none",
          animation: false,
          lineStyle: { color: palette.reference, width: 1, type: "dashed" },
          data: [
            reference(summary.meanDifference, "mean difference"),
            reference(summary.upperLimit, "+1.96 SD"),
            reference(summary.lowerLimit, "−1.96 SD"),
          ],
        },
      },
    ],
  };
}
