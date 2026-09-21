import { describe, expect, it } from "vitest";

import type { MetricValue } from "@/api/types";
import {
  differenceSummary,
  fiveNumber,
  groupValues,
  pairMetrics,
  pairingKey,
  quantile,
} from "@/lib/compare-model";

function metric(
  overrides: Partial<MetricValue> & Pick<MetricValue, "metric_id" | "derived_metric_id">,
): MetricValue {
  return {
    dataset_id: "white-cmj-acc-grf",
    metric_name: null,
    metric_description: null,
    si_unit: "m",
    measurement_class: "PIPELINE_DERIVED",
    value_kind: "scalar",
    value_num: 1,
    value_json: null,
    subject_id: "white-s000",
    session_id: "white-s000",
    trial_id: null,
    stream_id: null,
    entity_id: null,
    algorithm_id: "alg",
    algorithm_version: "1.0.0",
    parameters_hash: null,
    code_git_sha: null,
    run_id: "run",
    computed_at: null,
    provenance: {},
    ...overrides,
  } as MetricValue;
}

/** Two metrics of the same quantity, observed on the same three trials. */
const PAIRABLE = ["t0", "t1", "t2"].flatMap((trial, index) => [
  metric({
    metric_id: "source_jump_height",
    derived_metric_id: `dm-src-${trial}`,
    trial_id: trial,
    measurement_class: "SOURCE_DERIVED",
    value_num: 0.4 + index * 0.1,
  }),
  metric({
    metric_id: "cmj.jump_height_jhwd",
    derived_metric_id: `dm-pipe-${trial}`,
    trial_id: trial,
    value_num: 0.4 + index * 0.1 - 0.002,
  }),
]);

describe("pairing", () => {
  it("pairs only observations that share a full identity", () => {
    const result = pairMetrics(PAIRABLE, "source_jump_height", "cmj.jump_height_jhwd");
    expect(result.pairs).toHaveLength(3);
    expect(result.sameUnit).toBe(true);
    expect(result.pairs[0]?.a).toBeCloseTo(0.4, 9);
    expect(result.pairs[0]?.b).toBeCloseTo(0.398, 9);
    // Both sides keep their served row, so a pair stays traceable.
    expect(result.pairs[0]?.derivedMetricIdA).toBe("dm-src-t0");
    expect(result.pairs[0]?.derivedMetricIdB).toBe("dm-pipe-t0");
  });

  it("never pairs across datasets", () => {
    // Nothing links a subject in one source to a subject in another.
    const crossDataset = [
      metric({
        metric_id: "a",
        derived_metric_id: "dm-a",
        dataset_id: "one",
        trial_id: "t0",
      }),
      metric({
        metric_id: "b",
        derived_metric_id: "dm-b",
        dataset_id: "two",
        trial_id: "t0",
      }),
    ];
    expect(pairMetrics(crossDataset, "a", "b").pairs).toHaveLength(0);
    expect(pairingKey(crossDataset[0]!)).not.toBe(pairingKey(crossDataset[1]!));
  });

  it("drops an ambiguous key rather than guessing a pair", () => {
    const ambiguous = [
      metric({ metric_id: "a", derived_metric_id: "dm-a1", trial_id: "t0", value_num: 1 }),
      metric({ metric_id: "a", derived_metric_id: "dm-a2", trial_id: "t0", value_num: 2 }),
      metric({ metric_id: "b", derived_metric_id: "dm-b1", trial_id: "t0", value_num: 3 }),
    ];
    const result = pairMetrics(ambiguous, "a", "b");
    expect(result.pairs).toHaveLength(0);
    expect(result.unmatchedA).toBe(2);
  });

  it("reports a unit mismatch instead of subtracting incompatible quantities", () => {
    const mixed = [
      metric({ metric_id: "a", derived_metric_id: "dm-a", trial_id: "t0", si_unit: "m" }),
      metric({ metric_id: "b", derived_metric_id: "dm-b", trial_id: "t0", si_unit: "W/kg" }),
    ];
    const result = pairMetrics(mixed, "a", "b");
    expect(result.pairs).toHaveLength(1);
    expect(result.sameUnit).toBe(false);
    expect(result.unitA).toBe("m");
    expect(result.unitB).toBe("W/kg");
  });
});

describe("difference summary", () => {
  it("describes the spread of the plotted differences", () => {
    const { pairs } = pairMetrics(PAIRABLE, "source_jump_height", "cmj.jump_height_jhwd");
    const summary = differenceSummary(pairs);
    expect(summary?.count).toBe(3);
    expect(summary?.meanDifference).toBeCloseTo(-0.002, 6);
    // A constant offset has no spread, so the limits sit on the mean.
    expect(summary?.lowerLimit).toBeCloseTo(-0.002, 6);
    expect(summary?.upperLimit).toBeCloseTo(-0.002, 6);
    expect(summary?.proportionalBias).toBe(false);
    expect(summary?.points[0]?.[0]).toBeCloseTo(0.399, 6);
  });

  it("withholds classical limits when difference grows with magnitude", () => {
    const pairs = Array.from({ length: 10 }, (_value, index) => ({
      key: `pair-${index}`,
      label: `pair-${index}`,
      a: index + 1,
      b: (index + 1) * 1.2,
      derivedMetricIdA: `a-${index}`,
      derivedMetricIdB: `b-${index}`,
    }));
    const summary = differenceSummary(pairs);
    expect(summary?.proportionalBias).toBe(true);
    expect(summary?.biasCorrelation).toBeCloseTo(1, 9);
  });

  it("declines a spread below three pairs, where it would be noise", () => {
    const { pairs } = pairMetrics(PAIRABLE.slice(0, 4), "source_jump_height", "cmj.jump_height_jhwd");
    expect(pairs).toHaveLength(2);
    expect(differenceSummary(pairs)).toBeNull();
  });
});

describe("distribution", () => {
  it("groups served values and ignores rows with no value", () => {
    const rows = [
      metric({ metric_id: "m", derived_metric_id: "1", subject_id: "p1", value_num: 3 }),
      metric({ metric_id: "m", derived_metric_id: "2", subject_id: "p1", value_num: 1 }),
      metric({ metric_id: "m", derived_metric_id: "3", subject_id: "p2", value_num: 5 }),
      metric({ metric_id: "m", derived_metric_id: "4", subject_id: "p2", value_num: null }),
    ];
    const groups = groupValues(rows, "m", "subject_id");
    expect(groups.map((group) => [group.groupId, group.values])).toEqual([
      ["p1", [1, 3]],
      ["p2", [5]],
    ]);
  });

  it("summarises a sample with interpolated quartiles", () => {
    const summary = fiveNumber([1, 2, 3, 4, 5]);
    expect(summary).toEqual({ min: 1, q1: 2, median: 3, q3: 4, max: 5, count: 5 });
    expect(quantile([1, 2], 0.5)).toBeCloseTo(1.5, 9);
    expect(fiveNumber([])).toBeNull();
  });
});
