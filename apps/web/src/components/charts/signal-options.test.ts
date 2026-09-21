import { describe, expect, it } from "vitest";

import {
  buildSignalOption,
  canonicalSeconds,
  crossesZero,
  formatAxisTime,
  formatSignalValue,
  paneLayout,
  rangeLabel,
  reductionNote,
} from "@/components/charts/signal-options";
import {
  defaultGroupId,
  groupChannels,
} from "@/components/charts/signal-channels";
import { readPalette, seriesColor } from "@/lib/chart-palette";

const PALETTE = readPalette();

const OPTION = buildSignalOption({
  panes: [{ id: "force", label: "Ground reaction force", unit: "N" }],
  series: [
    {
      name: "Force Z (vertical)",
      unit: "N",
      measurementClass: "SOURCE_DERIVED",
      paneIndex: 0,
      points: [
        [0, -20],
        [10, 1],
        [20, null],
        [30, 3],
      ],
    },
  ],
  playheadMs: 12,
  rangeMs: { fromMs: 5, toMs: 25 },
  palette: PALETTE,
  originNs: -1_345_000_000n,
  timeReference: "takeoff",
});

function seriesOf(option: typeof OPTION) {
  return option.series as Array<Record<string, unknown>>;
}

describe("signal option builder", () => {
  it("draws exact polylines: no smoothing, no sampling, no gap bridging", () => {
    const trace = seriesOf(OPTION).find((entry) => entry.id === "series-0")!;
    expect(trace.type).toBe("line");
    expect(trace.smooth).toBe(false);
    expect(trace.sampling).toBe("none");
    expect(trace.connectNulls).toBe(false);
    expect(trace.data).toEqual([
      [0, -20],
      [10, 1],
      [20, null],
      [30, 3],
    ]);
    expect(OPTION.animation).toBe(false);
  });

  it("carries the playhead and range on an overlay, not on a toggleable trace", () => {
    // A reader can hide a series in the legend; the committed time and range
    // must survive that, so they ride their own silent carrier.
    const overlay = seriesOf(OPTION).find((entry) => entry.id === "overlay-0")!;
    const markLine = overlay.markLine as { data: Array<{ xAxis: number }> };
    expect(markLine.data).toEqual([{ xAxis: 12 }]);
    const markArea = overlay.markArea as { data: Array<Array<{ xAxis: number }>> };
    expect(markArea.data[0]?.[1]).toEqual({ xAxis: 25 });
    expect(overlay.silent).toBe(true);
  });

  it("labels the time axis against the canonical clock reference", () => {
    const xAxes = OPTION.xAxis as Array<{ name?: string }>;
    expect(xAxes[0]?.name).toBe("Time (s relative to takeoff)");
    const yAxes = OPTION.yAxis as Array<{ name: string }>;
    expect(yAxes[0]?.name).toBe("Ground reaction force [N]");
  });

  it("converts renderer-local milliseconds back to canonical seconds", () => {
    // A White CMJ trial is takeoff-aligned: its window starts at -1.345 s.
    expect(canonicalSeconds(-1_345_000_000n, 0)).toBeCloseTo(-1.345);
    expect(canonicalSeconds(-1_345_000_000n, 1345)).toBeCloseTo(0);
  });

  it("draws a zero reference only where the trace actually crosses it", () => {
    const trace = seriesOf(OPTION).find((entry) => entry.id === "series-0")!;
    expect((trace.markLine as { data: unknown[] }).data).toEqual([{ yAxis: 0 }]);
    expect(crossesZero([[0, 1], [1, 2]])).toBe(false);
    expect(crossesZero([[0, -1], [1, 2]])).toBe(true);
    expect(crossesZero([[0, null], [1, 3]])).toBe(false);
  });

  it("uses the semantic measurement color", () => {
    const trace = seriesOf(OPTION).find((entry) => entry.id === "series-0")!;
    expect(trace.color).toBe(PALETTE.measurement.SOURCE_DERIVED);
    expect(seriesColor(PALETTE, "PIPELINE_DERIVED")).toBe(PALETTE.measurement.PIPELINE_DERIVED);
  });

  it("formats values to a defensible precision for their magnitude", () => {
    expect(formatSignalValue(1234.5678, "N")).toBe("1234.6 N");
    expect(formatSignalValue(2.71828, "1")).toBe("2.72");
    expect(formatSignalValue(0.000123, "m")).toBe("0.0001 m");
    expect(formatSignalValue(Number.NaN, "m")).toBe("unavailable");
  });

  it("renders a reduced window as an extrema envelope, not as uncertainty", () => {
    const reduced = buildSignalOption({
      panes: [{ id: "position", label: "Position", unit: "m" }],
      series: [
        {
          name: "Velocity X",
          unit: "m/s",
          measurementClass: "MODEL_ESTIMATED",
          paneIndex: 0,
          points: [
            [0, 0],
            [10, 1],
          ],
        },
      ],
      bands: [
        {
          name: "Position X",
          unit: "m",
          measurementClass: "MODEL_ESTIMATED",
          paneIndex: 0,
          points: [
            [0, 0, 5],
            [10, 1, 7],
          ],
        },
      ],
      playheadMs: null,
      rangeMs: null,
      palette: PALETTE,
      originNs: 0n,
    });
    const bands = seriesOf(reduced).filter((entry) =>
      String(entry.id ?? "").startsWith("band-"),
    );
    expect(bands).toHaveLength(2);
    expect(bands[0]?.name).toBe("Position X — reduction envelope");
    expect(bands[1]?.name).toBe("Position X — envelope span");
    expect(bands[1]?.stack).toBe("band-0");
    // The legend never offers the span carrier as if it were a measurement.
    const legend = reduced.legend as { data?: string[] };
    expect(legend.data ?? []).not.toContain("Position X — envelope span");
  });
});

describe("time axis formatting", () => {
  it("keeps sub-second resolution for a jump trial", () => {
    // A White CMJ trial spans about 1.3 s and counts down to takeoff.
    expect(formatAxisTime(-1.2, 1.345)).toBe("-1.20");
    expect(formatAxisTime(0, 1.345)).toBe("0.00");
    expect(formatAxisTime(-12.5, 30)).toBe("-12.5");
  });

  it("switches to a minute clock for a match period", () => {
    expect(formatAxisTime(3570, 3022)).toBe("59:30");
    expect(formatAxisTime(0, 3022)).toBe("0:00");
    expect(formatAxisTime(65, 3022)).toBe("1:05");
  });

  it("keeps the sign of an event-aligned countdown", () => {
    expect(formatAxisTime(-125, 600)).toBe("-2:05");
  });
});

describe("pane layout", () => {
  it("reserves room for the legend and the shared range slider", () => {
    const [only] = paneLayout(1);
    expect(only!.topPercent).toBeGreaterThan(0);
    expect(only!.topPercent + only!.heightPercent).toBeLessThan(100);
  });

  it("stacks panes without overlapping them", () => {
    const layout = paneLayout(3);
    expect(layout).toHaveLength(3);
    for (let index = 1; index < layout.length; index += 1) {
      const previous = layout[index - 1]!;
      const current = layout[index]!;
      expect(current.topPercent).toBeGreaterThan(previous.topPercent + previous.heightPercent);
    }
  });
});

describe("channel grouping", () => {
  const FORCE_COLUMNS = [
    "force_x_n",
    "force_y_n",
    "force_z_n",
    "force_z_body_weight_ratio",
    "moment_x_n_m",
    "cop_x_m",
  ];
  const FORCE_UNITS = {
    force_x_n: "N",
    force_y_n: "N",
    force_z_n: "N",
    force_z_body_weight_ratio: "1",
    moment_x_n_m: "N*m",
    cop_x_m: "m",
  };

  it("keeps quantities with different units on different axes", () => {
    const groups = groupChannels(FORCE_COLUMNS, FORCE_UNITS);
    const units = new Map(groups.map((group) => [group.id, group.unit]));
    expect(units.get("force")).toBe("N");
    expect(units.get("body_weight_ratio")).toBe("1");
    expect(units.get("moment")).toBe("N*m");
    expect(units.get("cop")).toBe("m");
  });

  it("opens a force plate on the ground reaction force", () => {
    const groups = groupChannels(FORCE_COLUMNS, FORCE_UNITS);
    expect(defaultGroupId(groups, "force")).toBe("force");
  });

  it("opens an inertial unit on acceleration, not on the magnetometer", () => {
    const groups = groupChannels(
      ["mag_x_ut", "gyro_x_rad_s", "accel_x_m_s2", "temperature_deg_c"],
      {
        mag_x_ut: "uT",
        gyro_x_rad_s: "rad/s",
        accel_x_m_s2: "m/s**2",
        temperature_deg_c: "degC",
      },
    );
    expect(defaultGroupId(groups, "imu")).toBe("accel");
  });

  it("opens GNSS on speed over ground", () => {
    const groups = groupChannels(["latitude_deg", "speed_m_s", "hdop"], {
      latitude_deg: "deg",
      speed_m_s: "m/s",
      hdop: "1",
    });
    expect(defaultGroupId(groups, "gnss")).toBe("speed");
  });

  it("surfaces an unrecognised canonical measure instead of dropping it", () => {
    const groups = groupChannels(["novel_measure_kg"], { novel_measure_kg: "kg" });
    expect(groups).toHaveLength(1);
    expect(groups[0]?.channels[0]?.id).toBe("novel_measure_kg");
    expect(defaultGroupId(groups, "force")).toBe("novel_measure_kg");
  });

  it("names nothing when the window holds no measure", () => {
    expect(defaultGroupId([], "force")).toBeNull();
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
