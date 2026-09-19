import { describe, expect, it } from "vitest";

import {
  formatMetricValue,
  MEASUREMENT_CLASSES,
  QUALITY_STATES,
  qualityStateFor,
} from "@/lib/measurement";

describe("measurement-class semantics", () => {
  it("encodes each class with a distinct shape and semantic token", () => {
    const shapes = Object.values(MEASUREMENT_CLASSES).map((entry) => entry.shape);
    expect(new Set(shapes).size).toBe(shapes.length);
    for (const descriptor of Object.values(MEASUREMENT_CLASSES)) {
      expect(descriptor.token).toMatch(/^var\(--d-measurement-/);
      expect(descriptor.semantics.length).toBeGreaterThan(0);
    }
  });

  it("never lets class copy upgrade an estimate into a measurement", () => {
    expect(MEASUREMENT_CLASSES.MODEL_ESTIMATED.neverMeans.join(" ")).toContain(
      "not measured",
    );
    expect(MEASUREMENT_CLASSES.SOURCE_DERIVED.neverMeans.join(" ")).toContain(
      "not ground truth",
    );
  });
});

describe("quality mapping", () => {
  it("maps severity/state without hiding quarantine", () => {
    expect(qualityStateFor("INFO", "VALID")).toBe("valid");
    expect(qualityStateFor("WARNING", "VALID")).toBe("warning");
    expect(qualityStateFor("ERROR", "VALID")).toBe("quarantined");
    expect(qualityStateFor("WARNING", "QUARANTINED")).toBe("quarantined");
    expect(qualityStateFor("", "")).toBe("unavailable");
    expect(QUALITY_STATES.quarantined.glyph).not.toBe(QUALITY_STATES.valid.glyph);
  });
});

describe("deterministic metric formatting", () => {
  it("formats without locale grouping and preserves units", () => {
    expect(formatMetricValue(2.7, "rad").text).toBe("2.700 rad");
    expect(formatMetricValue(0.00042, "m").text).toBe("0.000420 m");
    expect(formatMetricValue(12345.6, "m").text).toBe("12345.6 m");
    expect(formatMetricValue(1.5, "1").text).toBe("1.500");
  });

  it("renders unavailable instead of zero for missing values", () => {
    expect(formatMetricValue(null, "m").text).toBe("unavailable");
    expect(formatMetricValue(Number.NaN, "m").valueText).toBe("—");
  });
});
