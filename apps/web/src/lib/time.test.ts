import { describe, expect, it } from "vitest";

import {
  clampNs,
  formatClockNs,
  formatDurationNs,
  formatNsDecimal,
  InvalidNanosecondsError,
  nsFromRendererTime,
  parseNs,
  rendererTimeMs,
  stepFrames,
  tryParseNs,
} from "@/lib/time";

describe("canonical nanosecond time", () => {
  it("parses exact decimal text and rejects non-integer forms", () => {
    expect(parseNs("2987480000000")).toBe(2_987_480_000_000n);
    for (const value of ["", "-1", "1.5", "1e3", "abc", " 1"]) {
      expect(() => parseNs(value)).toThrow(InvalidNanosecondsError);
      expect(tryParseNs(value)).toBeNull();
    }
    expect(tryParseNs(1234)).toBeNull();
  });

  it("round-trips through decimal URL text", () => {
    const value = 123_456_789_012_345n;
    expect(parseNs(formatNsDecimal(value))).toBe(value);
  });

  it("keeps float renderer coordinates relative to a viewport origin", () => {
    const origin = 2_987_480_000_000n;
    const t = origin + 12_345_000n;
    const ms = rendererTimeMs(origin, t);
    expect(ms).toBeCloseTo(12.345, 9);
    expect(nsFromRendererTime(origin, ms)).toBe(t);
    // Large absolute values never enter renderer coordinates.
    expect(nsFromRendererTime(0n, rendererTimeMs(origin, t))).not.toBe(t);
  });

  it("formats durations and clocks deterministically", () => {
    expect(formatDurationNs(1_250_000_000n)).toBe("1.250 s");
    expect(formatDurationNs(45_000_000n)).toBe("45.000 ms");
    expect(formatDurationNs(1_200n)).toBe("1.2 µs");
    expect(formatDurationNs(999n)).toBe("999 ns");
    expect(formatClockNs(3_723_004_000_000n)).toBe("01:02:03.004");
  });

  it("steps by nominal frames and clamps to a range", () => {
    expect(stepFrames(1_000_000_000n, 1, 25)).toBe(1_040_000_000n);
    expect(stepFrames(1_000_000_000n, -2, 25)).toBe(920_000_000n);
    expect(stepFrames(1_000_000_000n, 1, 0)).toBe(1_000_000_000n);
    expect(clampNs(5n, 0n, 3n)).toBe(3n);
    expect(clampNs(-5n, 0n, 3n)).toBe(0n);
  });
});
