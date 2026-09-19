/**
 * Pure ECharts option builders for the signal laboratory.
 *
 * Rules encoded here: exact polylines (no smoothing), units on axes, separated
 * source/derived/model colors, visible playhead and selected range, deterministic
 * tooltip formatting, no decorative animation, and an explicit min/max envelope
 * representation when the served window is display-reduced.
 */

import type { EChartsOption, LineSeriesOption, SeriesOption } from "echarts";

import { seriesColor, type ChartPalette } from "@/lib/chart-palette";
import { formatDurationNs, rendererTimeMs } from "@/lib/time";

export interface SignalSeries {
  readonly name: string;
  readonly unit: string;
  readonly measurementClass: string | null;
  /** [milliseconds from the window origin, value]; null keeps an observed gap. */
  readonly points: ReadonlyArray<readonly [number, number | null]>;
}

export interface SignalBand {
  readonly name: string;
  readonly unit: string;
  readonly measurementClass: string | null;
  /** min/max envelope: [ms, min, max]. */
  readonly points: ReadonlyArray<readonly [number, number | null, number | null]>;
}

export interface BuildSignalOptionInput {
  readonly series: readonly SignalSeries[];
  readonly bands?: readonly SignalBand[];
  readonly playheadMs: number | null;
  readonly rangeMs: { readonly fromMs: number; readonly toMs: number } | null;
  readonly palette: ChartPalette;
}

const MAX_VALUE_AXES = 3;

function axisIndexForUnits(units: readonly string[], unit: string): number {
  const unique = Array.from(new Set(units));
  if (unique.length > MAX_VALUE_AXES) return 0;
  const index = unique.indexOf(unit);
  return index < 0 ? 0 : index;
}

function axisFor(index: number): {
  yAxisIndex: number;
  axisName: string;
  position: "left" | "right";
  offset: number;
} {
  return {
    yAxisIndex: index,
    axisName: "",
    position: index === 0 ? "left" : "right",
    offset: index < 2 ? 0 : 48,
  };
}

/** Build the analytical option for reviewed signal windows. */
export function buildSignalOption(input: BuildSignalOptionInput): EChartsOption {
  const { palette, playheadMs, rangeMs } = input;
  const units = [
    ...input.series.map((series) => series.unit),
    ...(input.bands ?? []).map((band) => band.unit),
  ].filter((unit) => unit !== "1");
  const uniqueUnits = Array.from(new Set(units));
  const axisCount = Math.min(Math.max(uniqueUnits.length, 1), MAX_VALUE_AXES);

  const series: SeriesOption[] = [];
  input.series.forEach((entry, index) => {
    const axis = axisIndexForUnits(units, entry.unit);
    const line: LineSeriesOption = {
      id: `series-${index}`,
      name: entry.name,
      type: "line",
      yAxisIndex: axisCount > 1 ? axis : 0,
      showSymbol: false,
      smooth: false,
      sampling: "none",
      connectNulls: false,
      animation: false,
      color: seriesColor(palette, entry.measurementClass, index),
      lineStyle: { width: 1.4 },
      data: entry.points.map(([x, value]) => [x, value]),
    };
    if (index === 0) {
      line.markLine = {
        silent: true,
        symbol: "none",
        animation: false,
        label: {
          show: playheadMs !== null,
          formatter: "playhead",
          color: palette.playhead,
          fontSize: 10,
        },
        lineStyle: { color: palette.playhead, width: 1, type: "solid" },
        data: playheadMs !== null ? [{ xAxis: playheadMs }] : [],
      };
      if (rangeMs) {
        line.markArea = {
          silent: true,
          itemStyle: { color: palette.brush },
          data: [[{ xAxis: rangeMs.fromMs }, { xAxis: rangeMs.toMs }]],
        };
      }
    }
    series.push(line);
  });

  (input.bands ?? []).forEach((band, bandIndex) => {
    const axis = axisIndexForUnits(units, band.unit);
    const color = seriesColor(palette, band.measurementClass, input.series.length + bandIndex);
    const minName = `${band.name} (min)`;
    const spanName = `${band.name} (max−min)`;
    series.push({
      id: `band-${bandIndex}-min`,
      name: minName,
      type: "line",
      yAxisIndex: axisCount > 1 ? axis : 0,
      showSymbol: false,
      smooth: false,
      sampling: "none",
      connectNulls: false,
      animation: false,
      color,
      lineStyle: { width: 1.2 },
      stack: `band-${bandIndex}`,
      data: band.points.map(([x, min]) => [x, min]),
    });
    series.push({
      id: `band-${bandIndex}-span`,
      name: spanName,
      type: "line",
      yAxisIndex: axisCount > 1 ? axis : 0,
      showSymbol: false,
      smooth: false,
      sampling: "none",
      connectNulls: false,
      animation: false,
      color,
      lineStyle: { width: 0, opacity: 0.25 },
      areaStyle: { color, opacity: 0.18 },
      stack: `band-${bandIndex}`,
      data: band.points.map(([x, min, max]) => [
        x,
        min === null || max === null ? null : max - min,
      ]),
    });
  });

  const yAxes = Array.from({ length: axisCount }, (_value, index) => {
    const axis = axisFor(index);
    const unit = uniqueUnits[index] ?? "";
    return {
      type: "value" as const,
      position: axis.position,
      offset: axis.offset,
      name: unit === "" ? "" : `[${unit}]`,
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      axisLabel: { color: palette.axis, fontSize: 10 },
      splitLine: {
        show: index === 0,
        lineStyle: { color: palette.grid, width: 1 },
      },
      axisLine: { show: true, lineStyle: { color: palette.border } },
    };
  });

  return {
    animation: false,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      decal: { show: false },
      description: "Signal window with exact samples, playhead and selected range.",
    },
    grid: {
      left: 56,
      right: axisCount > 1 ? 64 : 20,
      top: input.series.length + (input.bands?.length ?? 0) > 1 ? 46 : 18,
      bottom: 44,
      containLabel: false,
    },
    legend:
      input.series.length + (input.bands?.length ?? 0) > 1
        ? {
            top: 4,
            textStyle: { color: palette.textMuted, fontSize: 10 },
            inactiveColor: palette.axis,
          }
        : { show: false },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", label: { backgroundColor: palette.surface } },
      backgroundColor: palette.surface,
      borderColor: palette.border,
      textStyle: { color: palette.text, fontSize: 11 },
      valueFormatter: (value: unknown) =>
        typeof value === "number" && Number.isFinite(value) ? value.toFixed(3) : "—",
    },
    xAxis: {
      type: "value",
      name: "ms from window start",
      nameTextStyle: { color: palette.textMuted, fontSize: 10 },
      min: "dataMin",
      max: "dataMax",
      axisLabel: { color: palette.axis, fontSize: 10 },
      axisLine: { lineStyle: { color: palette.border } },
      splitLine: { lineStyle: { color: palette.grid } },
    },
    yAxis: yAxes,
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      {
        type: "slider",
        xAxisIndex: 0,
        height: 16,
        bottom: 4,
        borderColor: palette.border,
        fillerColor: palette.brush,
        backgroundColor: "transparent",
        dataBackground: {
          lineStyle: { color: palette.axis, opacity: 0.4 },
          areaStyle: { color: palette.axis, opacity: 0.1 },
        },
        textStyle: { color: palette.textMuted, fontSize: 9 },
      },
    ],
    series,
  };
}

/** Header note for a display-reduced window; null when samples are exact. */
export function reductionNote(meta: {
  readonly reduction: { readonly method: string; readonly source_points: number; readonly returned_points: number } | null;
}): string | null {
  if (!meta.reduction) return null;
  return `Display-reduced: ${meta.reduction.method}, ${meta.reduction.source_points} source points → ${meta.reduction.returned_points} envelope points; metrics never derive from this view.`;
}

/** Convert an artifact window's rows into renderer-local series points. */
export function toPoints(
  rows: ReadonlyArray<Record<string, unknown>>,
  valueKey: string,
  originNs: bigint,
): Array<readonly [number, number | null]> {
  const points: Array<readonly [number, number | null]> = [];
  for (const row of rows) {
    const t = row["t_rel_ns"];
    if (typeof t !== "number" && typeof t !== "bigint") continue;
    const value = row[valueKey];
    points.push([
      rendererTimeMs(originNs, BigInt(t)),
      typeof value === "number" && Number.isFinite(value) ? value : null,
    ]);
  }
  return points;
}

export function rangeLabel(fromNs: bigint | null, toNs: bigint | null): string {
  if (fromNs === null || toNs === null) return "full window";
  return `${formatDurationNs(toNs - fromNs)} selected`;
}

export const IDENTITY_COLUMNS: readonly string[] = [
  "dataset_id",
  "session_id",
  "trial_id",
  "subject_id",
  "device_id",
  "stream_id",
  "entity_id",
  "object_id",
  "object_type",
  "group_id",
  "sample_index",
  "t_rel_ns",
  "timestamp_utc_ns",
  "nominal_sampling_rate_hz",
  "measurement_class",
  "clock_id",
  "synchronization_spec_id",
  "coordinate_frame_id",
  "skeleton_id",
];

/** Reduced display columns pair as `<measure>_min` / `<measure>_max`. */
export function detectBands(
  columns: readonly string[],
): Array<{ base: string; minKey: string; maxKey: string }> {
  const names = new Set(columns);
  const bands: Array<{ base: string; minKey: string; maxKey: string }> = [];
  for (const column of columns) {
    if (!column.endsWith("_min")) continue;
    const base = column.slice(0, -"_min".length);
    const maxKey = `${base}_max`;
    if (names.has(maxKey)) bands.push({ base, minKey: column, maxKey });
  }
  return bands;
}

/**
 * Numeric measure columns of a window: excludes identity/time columns, the
 * min/max envelope members (rendered as bands) and non-numeric flags.
 */
export function measureColumns(
  columns: readonly string[],
  units: Readonly<Record<string, string>>,
  sampleRow: Record<string, unknown> | undefined,
): string[] {
  const bandMembers = new Set(detectBands(columns).flatMap((band) => [band.minKey, band.maxKey]));
  return columns.filter((column) => {
    if (IDENTITY_COLUMNS.includes(column) || bandMembers.has(column)) return false;
    if (Object.prototype.hasOwnProperty.call(units, column)) {
      return column !== "t_rel_ns" && column !== "timestamp_utc_ns";
    }
    const value = sampleRow?.[column];
    return typeof value === "number";
  });
}
