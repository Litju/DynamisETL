import { describe, expect, it } from "vitest";

import {
  buildSignalOption,
  detectBands,
  measureColumns,
  rangeLabel,
  reductionNote,
  toPoints,
} from "@/components/charts/signal-options";
import { readPalette, seriesColor } from "@/lib/chart-palette";

const PALETTE = readPalette();

describe("signal option builder", () => {
  const option = buildSignalOption({
    series: [
      {
        name: "x_m",
        unit: "m",
        measurementClass: "MODEL_ESTIMATED",
        points: [
          [0, 0],
          [10, 1],
          [20, null],
          [30, 3],
        ],
      },
    ],
    playheadMs: 12,
    rangeMs: { fromMs: 5, toMs: 25 },
    palette: PALETTE,
  });

  it("draws exact polylines: no smoothing, no sampling, no gap bridging", () => {
    const series = (option.series as Array<Record<string, unknown>>)[0]!;
    expect(series.type).toBe("line");
    expect(series.smooth).toBe(false);
    expect(series.sampling).toBe("none");
    expect(series.connectNulls).toBe(false);
    expect(series.data).toEqual([
      [0, 0],
      [10, 1],
      [20, null],
      [30, 3],
    ]);
    expect(option.animation).toBe(false);
  });

  it("marks the playhead and the committed range and labels the x axis", () => {
    const series = (option.series as Array<Record<string, unknown>>)[0]!;
    const markLine = series.markLine as { data: Array<{ xAxis: number }> };
    expect(markLine.data).toEqual([{ xAxis: 12 }]);
    const markArea = series.markArea as { data: Array<Array<{ xAxis: number }>> };
    expect(markArea.data[0]?.[1]).toEqual({ xAxis: 25 });
    expect((option.xAxis as { name: string }).name).toContain("ms from window start");
    expect((option.yAxis as Array<{ name: string }>)[0]?.name).toBe("[m]");
  });

  it("omits the playhead mark when no time is committed", () => {
    const without = buildSignalOption({
      series: [],
      playheadMs: null,
      rangeMs: null,
      palette: PALETTE,
    });
    expect(without.series).toEqual([]);
  });

  it("renders a reduced window as an extrema envelope", () => {
    const reduced = buildSignalOption({
      series: [],
      bands: [
        {
          name: "x_m",
          unit: "m",
          measurementClass: "MODEL_ESTIMATED",
          points: [
            [0, 0, 5],
            [10, 1, 7],
          ],
        },
      ],
      playheadMs: null,
      rangeMs: null,
      palette: PALETTE,
    });
    const series = reduced.series as Array<Record<string, unknown>>;
    expect(series).toHaveLength(2);
    expect(series[0]?.name).toBe("x_m (min)");
    expect(series[1]?.name).toBe("x_m (max−min)");
    expect((series[1] as { areaStyle: { opacity: number } }).areaStyle.opacity).toBeCloseTo(0.18);
    expect(series[1]?.stack).toBe("band-0");
  });

  it("uses the semantic measurement color and keeps legend/tooltips deterministic", () => {
    const series = (option.series as Array<Record<string, unknown>>)[0]!;
    expect(series.color).toBe(PALETTE.measurement.MODEL_ESTIMATED);
    expect(seriesColor(PALETTE, "PIPELINE_DERIVED")).toBe(
      PALETTE.measurement.PIPELINE_DERIVED,
    );
    const tooltip = option.tooltip as { valueFormatter: (value: unknown) => string };
    expect(tooltip.valueFormatter(1.23456)).toBe("1.235");
    expect(tooltip.valueFormatter(null)).toBe("—");
  });
});

describe("window column selection", () => {
  it("detects min/max envelope pairs and ignores unpaired columns", () => {
    expect(
      detectBands(["t_rel_ns", "x_m_min", "x_m_max", "y_m_min", "y_m_max", "z_min"]),
    ).toEqual([
      { base: "x_m", minKey: "x_m_min", maxKey: "x_m_max" },
      { base: "y_m", minKey: "y_m_min", maxKey: "y_m_max" },
    ]);
  });

  it("selects numeric measures and excludes identity, time and band members", () => {
    const columns = [
      "dataset_id",
      "subject_id",
      "t_rel_ns",
      "sample_index",
      "x_m",
      "x_m_min",
      "x_m_max",
      "flag",
    ];
    const units = { x_m: "m", x_m_min: "m", x_m_max: "m" };
    expect(measureColumns(columns, units, { flag: true })).toEqual(["x_m"]);
    expect(measureColumns(["a", "b"], {}, { a: 1, b: "text" })).toEqual(["a"]);
  });

  it("converts rows to renderer-local ms points with explicit gaps", () => {
    const points = toPoints(
      [
        { t_rel_ns: 1_000_000_000, v: 1 },
        { t_rel_ns: 2_000_000_000, v: Number.NaN },
      ],
      "v",
      1_000_000_000n,
    );
    expect(points).toEqual([
      [0, 1],
      [1000, null],
    ]);
  });
});

describe("display reduction communication", () => {
  it("states the reduction and its scientific non-use when reduced", () => {
    const note = reductionNote({
      reduction: {
        method: "min_max_envelope_per_time_bucket",
        source_points: 1000,
        returned_points: 120,
      },
    });
    expect(note).toContain("Display-reduced");
    expect(note).toContain("1000 source points → 120 envelope points");
    expect(note).toContain("metrics never derive from this view");
  });

  it("says nothing when samples are exact", () => {
    expect(reductionNote({ reduction: null })).toBeNull();
  });

  it("labels a committed range explicitly", () => {
    expect(rangeLabel(0n, 2_500_000_000n)).toBe("2.500 s selected");
    expect(rangeLabel(null, null)).toBe("full window");
  });
});
