/**
 * Pure ECharts option builders for the signal laboratory.
 *
 * Rules encoded here: exact polylines (no smoothing), unit-aware axes, one grid
 * per physical quantity so a ratio never shares a scale with a moment, a shared
 * time axis with a linked pointer, separated source/derived/model colors, a
 * visible playhead and selected range, deterministic tooltip formatting, no
 * decorative animation, and an explicit min/max envelope representation that
 * reads as display reduction rather than measured uncertainty.
 */

import type { EChartsOption, LineSeriesOption, SeriesOption } from "echarts";

import { seriesColor, type ChartPalette } from "@/lib/chart-palette";
import { formatDurationNs } from "@/lib/time";

export interface SignalSeries {
  readonly name: string;
  readonly unit: string;
  readonly measurementClass: string | null;
  /** Index of the pane this series belongs to. */
  readonly paneIndex: number;
  /** [milliseconds from the window origin, value]; null keeps an observed gap. */
  readonly points: ReadonlyArray<readonly [number, number | null]>;
}

export interface SignalBand {
  readonly name: string;
  readonly unit: string;
  readonly measurementClass: string | null;
  readonly paneIndex: number;
  /** min/max envelope: [ms, min, max]. */
  readonly points: ReadonlyArray<readonly [number, number | null, number | null]>;
}

export interface SignalPane {
  readonly id: string;
  readonly label: string;
  readonly unit: string;
}

export interface BuildSignalOptionInput {
  readonly panes: readonly SignalPane[];
  readonly series: readonly SignalSeries[];
  readonly bands?: readonly SignalBand[];
  readonly playheadMs: number | null;
  readonly rangeMs: { readonly fromMs: number; readonly toMs: number } | null;
  readonly palette: ChartPalette;
  /** Canonical time of the window origin, for axis labels in real seconds. */
  readonly originNs: bigint;
  /** What the canonical clock counts from, e.g. "takeoff". */
  readonly timeReference?: string | undefined;
}

/** Share of the canvas reserved for the legend above the panes. */
const TOP_RESERVE_PERCENT = 9;
/** Share reserved for the shared time axis and range slider below them. */
const BOTTOM_RESERVE_PERCENT = 15;
/** Share between two stacked panes, enough for the upper axis labels. */
const PANE_GAP_PERCENT = 7;
const LEGEND_HEIGHT = 20;

/** Seconds of canonical time at a renderer-local millisecond offset. */
export function canonicalSeconds(originNs: bigint, ms: number): number {
  return Number(originNs) / 1e9 + ms / 1e3;
}

/** A span beyond this reads better as minutes and seconds than as seconds. */
const CLOCK_AXIS_THRESHOLD_S = 120;

/**
 * Format a canonical time for the shared axis.
 *
 * A jump trial spans about a second, a match period spans fifty minutes. Bare
 * seconds are precise for the first and unreadable for the second, so a long
 * window switches to a minute clock while a short one keeps sub-second
 * resolution. Negative times keep their sign: an event-aligned trial counts
 * down to its reference.
 */
export function formatAxisTime(seconds: number, spanSeconds: number): string {
  if (!Number.isFinite(seconds)) return "";
  if (spanSeconds < CLOCK_AXIS_THRESHOLD_S) {
    return seconds.toFixed(spanSeconds < 10 ? 2 : 1);
  }
  const negative = seconds < 0;
  const total = Math.abs(seconds);
  const minutes = Math.floor(total / 60);
  const rest = Math.floor(total % 60);
  return `${negative ? "-" : ""}${minutes}:${String(rest).padStart(2, "0")}`;
}

/** Deterministic axis/tooltip number formatting, scaled to the magnitude. */
export function formatSignalValue(value: number, unit: string): string {
  if (!Number.isFinite(value)) return "unavailable";
  const magnitude = Math.abs(value);
  const digits = magnitude === 0 ? 2 : magnitude >= 100 ? 1 : magnitude >= 1 ? 2 : 4;
  const text = value.toFixed(digits);
  return unit === "1" ? text : `${text} ${unit}`;
}

/**
 * Vertical layout for `paneCount` stacked panes sharing one time axis.
 *
 * Percentages rather than pixels, so the panes keep their proportions when the
 * workbench pane is resized. The reserves keep the legend and the range slider
 * out of the plotted area instead of overlapping the trace.
 */
export function paneLayout(
  paneCount: number,
): Array<{ topPercent: number; heightPercent: number }> {
  const count = Math.max(1, paneCount);
  const gaps = PANE_GAP_PERCENT * (count - 1);
  const available = 100 - TOP_RESERVE_PERCENT - BOTTOM_RESERVE_PERCENT - gaps;
  const heightPercent = available / count;
  return Array.from({ length: count }, (_value, index) => ({
    topPercent: TOP_RESERVE_PERCENT + index * (heightPercent + PANE_GAP_PERCENT),
    heightPercent,
  }));
}

/** Build the analytical option for reviewed signal windows. */
export function buildSignalOption(input: BuildSignalOptionInput): EChartsOption {
  const { palette, playheadMs, rangeMs, originNs } = input;
  const panes = input.panes.length > 0 ? input.panes : [{ id: "none", label: "", unit: "1" }];
  const layout = paneLayout(panes.length);
  const spanSeconds = windowSpanSeconds(input.series, input.bands ?? []);

  const grids = layout.map((slot) => ({
    left: 76,
    right: 28,
    top: `${slot.topPercent.toFixed(3)}%`,
    height: `${slot.heightPercent.toFixed(3)}%`,
    containLabel: false,
  }));

  const xAxes = panes.map((_pane, index) => ({
    type: "value" as const,
    gridIndex: index,
    min: "dataMin" as const,
    max: "dataMax" as const,
    // Only the bottom pane carries tick labels; the panes share one time axis.
    axisLabel: {
      show: index === panes.length - 1,
      color: palette.axis,
      fontSize: 10,
      formatter: (value: number) =>
        formatAxisTime(canonicalSeconds(originNs, value), spanSeconds),
    },
    axisLine: { lineStyle: { color: palette.border } },
    axisTick: { show: index === panes.length - 1, lineStyle: { color: palette.border } },
    splitLine: { show: true, lineStyle: { color: palette.grid, type: "dashed" as const } },
    ...(index === panes.length - 1
      ? {
          name: input.timeReference
            ? `Time (s relative to ${input.timeReference})`
            : "Time (s)",
          nameLocation: "middle" as const,
          nameGap: 26,
          nameTextStyle: { color: palette.textMuted, fontSize: 10 },
        }
      : {}),
  }));

  const yAxes = panes.map((pane, index) => ({
    type: "value" as const,
    gridIndex: index,
    scale: true,
    name: pane.unit === "1" ? pane.label : `${pane.label} [${pane.unit}]`,
    nameLocation: "end" as const,
    nameGap: 12,
    nameTextStyle: {
      color: palette.textMuted,
      fontSize: 10,
      align: "left" as const,
    },
    axisLabel: {
      color: palette.axis,
      fontSize: 10,
      formatter: (value: number) => formatSignalValue(value, "1"),
    },
    axisLine: { show: true, lineStyle: { color: palette.border } },
    splitLine: { show: true, lineStyle: { color: palette.grid } },
  }));

  const series: SeriesOption[] = [];

  // The reduction envelope is drawn first and subdued so it reads as the
  // background of the trace it summarizes, never as measured uncertainty.
  (input.bands ?? []).forEach((band, bandIndex) => {
    const color = seriesColor(palette, band.measurementClass, input.series.length + bandIndex);
    const shared = {
      type: "line" as const,
      xAxisIndex: band.paneIndex,
      yAxisIndex: band.paneIndex,
      showSymbol: false,
      smooth: false,
      sampling: "none" as const,
      connectNulls: false,
      animation: false,
      color,
      stack: `band-${bandIndex}`,
      silent: true,
    };
    series.push({
      ...shared,
      id: `band-${bandIndex}-min`,
      name: `${band.name} — reduction envelope`,
      lineStyle: { width: 0.8, opacity: 0.5 },
      data: band.points.map(([x, min]) => [x, min]),
    });
    series.push({
      ...shared,
      id: `band-${bandIndex}-span`,
      name: `${band.name} — envelope span`,
      lineStyle: { width: 0, opacity: 0 },
      areaStyle: { color, opacity: 0.16 },
      data: band.points.map(([x, min, max]) => [
        x,
        min === null || max === null ? null : max - min,
      ]),
      legendHoverLink: false,
    });
  });

  input.series.forEach((entry, index) => {
    const line: LineSeriesOption = {
      id: `series-${index}`,
      name: entry.name,
      type: "line",
      xAxisIndex: entry.paneIndex,
      yAxisIndex: entry.paneIndex,
      showSymbol: false,
      smooth: false,
      sampling: "none",
      connectNulls: false,
      animation: false,
      color: seriesColor(palette, entry.measurementClass, index),
      lineStyle: { width: 1.4 },
      data: entry.points.map(([x, value]) => [x, value]),
      // A zero line is a reference an analyst reads against; it is drawn only
      // where the data actually crosses it.
      markLine: {
        silent: true,
        symbol: "none",
        animation: false,
        label: { show: false },
        lineStyle: { color: palette.reference, width: 1, type: "dashed" },
        data: crossesZero(entry.points) ? [{ yAxis: 0 }] : [],
      },
    };
    series.push(line);
  });

  // The playhead and the committed range belong to the whole time axis, so they
  // are carried by one invisible series per pane rather than by a data series
  // that might be toggled off in the legend.
  panes.forEach((_pane, index) => {
    series.push({
      id: `overlay-${index}`,
      type: "line",
      xAxisIndex: index,
      yAxisIndex: index,
      data: [],
      silent: true,
      animation: false,
      legendHoverLink: false,
      markLine: {
        silent: true,
        symbol: "none",
        animation: false,
        label:
          index === 0 && playheadMs !== null
            ? {
                show: true,
                formatter: "playhead",
                color: palette.playhead,
                fontSize: 10,
                position: "insideEndTop" as const,
              }
            : { show: false },
        lineStyle: { color: palette.playhead, width: 1.2, type: "solid" },
        data: playheadMs !== null ? [{ xAxis: playheadMs }] : [],
      },
      markArea: rangeMs
        ? {
            silent: true,
            itemStyle: { color: palette.brush },
            data: [[{ xAxis: rangeMs.fromMs }, { xAxis: rangeMs.toMs }]],
          }
        : undefined,
    } as SeriesOption);
  });

  const unitBySeriesName = new Map(
    input.series.map((entry) => [entry.name, entry.unit] as const),
  );

  return {
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      decal: { show: false },
      description:
        "Signal window with exact canonical samples, a shared time axis, the committed playhead and the selected range.",
    },
    grid: grids,
    legend:
      input.series.length + (input.bands?.length ?? 0) > 1
        ? {
            type: "scroll",
            top: 6,
            height: LEGEND_HEIGHT,
            itemWidth: 14,
            itemHeight: 8,
            textStyle: { color: palette.textMuted, fontSize: 10 },
            inactiveColor: palette.axis,
            // Overlay carriers are structure, not data; they never appear.
            data: [
              ...input.series.map((entry) => entry.name),
              ...(input.bands ?? []).map((band) => `${band.name} — reduction envelope`),
            ],
          }
        : { show: false },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      label: { backgroundColor: palette.surface, color: palette.text, fontSize: 10 },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", label: { backgroundColor: palette.surface } },
      backgroundColor: palette.surface,
      borderColor: palette.border,
      borderWidth: 1,
      textStyle: { color: palette.text, fontSize: 11 },
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = rows[0] as { value?: [number, number] } | undefined;
        const ms = Array.isArray(first?.value) ? Number(first.value[0]) : Number.NaN;
        const header = Number.isFinite(ms)
          ? `${canonicalSeconds(originNs, ms).toFixed(3)} s`
          : "";
        const lines = rows
          .filter((row): row is { seriesName: string; value: [number, number] } => {
            const candidate = row as { seriesName?: string; value?: unknown };
            return (
              typeof candidate.seriesName === "string" &&
              !candidate.seriesName.startsWith("overlay") &&
              Array.isArray(candidate.value)
            );
          })
          .map((row) => {
            const unit = unitBySeriesName.get(row.seriesName) ?? "1";
            const value = Number(row.value[1]);
            return `${row.seriesName}: ${formatSignalValue(value, unit)}`;
          });
        return [header, ...lines].filter(Boolean).join("<br/>");
      },
    },
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: panes.map((_pane, index) => index),
        filterMode: "none",
      },
      {
        type: "slider",
        xAxisIndex: panes.map((_pane, index) => index),
        height: 18,
        bottom: 6,
        borderColor: palette.border,
        fillerColor: palette.brush,
        backgroundColor: "transparent",
        handleStyle: { color: palette.axis, borderColor: palette.border },
        moveHandleStyle: { color: palette.axis },
        dataBackground: {
          lineStyle: { color: palette.axis, opacity: 0.4 },
          areaStyle: { color: palette.axis, opacity: 0.1 },
        },
        labelFormatter: (value: number) =>
          formatAxisTime(canonicalSeconds(originNs, value), spanSeconds),
        textStyle: { color: palette.textMuted, fontSize: 9 },
      },
    ],
    series,
  };
}

/** Observed time span of a window, in seconds, across every plotted trace. */
export function windowSpanSeconds(
  series: readonly SignalSeries[],
  bands: readonly SignalBand[],
): number {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const entry of series) {
    for (const [ms] of entry.points) {
      if (ms < min) min = ms;
      if (ms > max) max = ms;
    }
  }
  for (const band of bands) {
    for (const [ms] of band.points) {
      if (ms < min) min = ms;
      if (ms > max) max = ms;
    }
  }
  return Number.isFinite(min) && Number.isFinite(max) ? (max - min) / 1e3 : 0;
}

/** True when a trace has observed values on both sides of zero. */
export function crossesZero(
  points: ReadonlyArray<readonly [number, number | null]>,
): boolean {
  let negative = false;
  let positive = false;
  for (const [, value] of points) {
    if (value === null || !Number.isFinite(value)) continue;
    if (value < 0) negative = true;
    else if (value > 0) positive = true;
    if (negative && positive) return true;
  }
  return false;
}

/** Header note for a display-reduced window; null when samples are exact. */
export function reductionNote(meta: {
  readonly reduction: {
    readonly method: string;
    readonly source_points: number;
    readonly returned_points: number;
  } | null;
}): string | null {
  if (!meta.reduction) return null;
  return `Display-reduced: ${meta.reduction.method}, ${meta.reduction.source_points} source points → ${meta.reduction.returned_points} envelope points; metrics never derive from this view.`;
}

export function rangeLabel(fromNs: bigint | null, toNs: bigint | null): string {
  if (fromNs === null || toNs === null) return "full window";
  return `${formatDurationNs(toNs - fromNs)} selected`;
}

