import { describe, expect, it } from "vitest";

import type { MetricValue } from "@/api/types";
import {
  discriminatingField,
  headlineMetricId,
  leadingFact,
  rankMetric,
  zoneBreakdown,
} from "@/lib/overview-summaries";

function metric(overrides: Partial<MetricValue> & Pick<MetricValue, "metric_id">): MetricValue {
  return {
    derived_metric_id: `dm-${overrides.metric_id}-${overrides.subject_id ?? overrides.trial_id ?? "x"}`,
    dataset_id: "d",
    metric_name: null,
    metric_description: null,
    si_unit: "m",
    measurement_class: "PIPELINE_DERIVED",
    value_kind: "scalar",
    value_num: 1,
    value_json: null,
    subject_id: null,
    session_id: "s",
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

const LOCOMOTOR = ["p1", "p2", "p3"].flatMap((subject, index) => [
  metric({
    metric_id: "locomotor.distance_total",
    metric_name: "Total locomotor distance",
    subject_id: subject,
    value_num: 10000 - index * 1000,
  }),
  metric({
    metric_id: "locomotor.distance_zone.low",
    subject_id: subject,
    value_num: 5000 - index * 100,
  }),
  metric({
    metric_id: "locomotor.distance_zone.medium",
    subject_id: subject,
    value_num: 3000 - index * 100,
  }),
  metric({
    metric_id: "locomotor.distance_zone.high",
    subject_id: subject,
    value_num: 2000 - index * 800,
  }),
]);

// One participant, eight trials: the subject is constant and cannot rank.
const CMJ = ["t0", "t1", "t2"].map((trial, index) =>
  metric({
    metric_id: "cmj.jump_height_jhwd",
    metric_name: "Jump height, onset-to-apex",
    subject_id: "white-s000",
    trial_id: `white-s000-${trial}`,
    value_num: 0.4 + index * 0.05,
  }),
);

describe("headline metric choice", () => {
  it("leads with the metric a reader of that domain looks at first", () => {
    expect(headlineMetricId(LOCOMOTOR)).toBe("locomotor.distance_total");
    expect(headlineMetricId(CMJ)).toBe("cmj.jump_height_jhwd");
  });

  it("falls back to the broadest served metric outside the known vocabulary", () => {
    const rows = [
      metric({ metric_id: "novel.b", subject_id: "p1" }),
      metric({ metric_id: "novel.a", subject_id: "p1" }),
      metric({ metric_id: "novel.a", subject_id: "p2" }),
    ];
    expect(headlineMetricId(rows)).toBe("novel.a");
  });

  it("names nothing when no value is served", () => {
    expect(headlineMetricId([])).toBeNull();
    expect(rankMetric([], "anything")).toBeNull();
  });
});

describe("entity discrimination", () => {
  it("ranks locomotor metrics by the player they belong to", () => {
    expect(discriminatingField(LOCOMOTOR)).toBe("subject_id");
  });

  it("ranks repeated trials of one participant by trial", () => {
    // Ranking on the constant subject would draw identically labelled bars.
    expect(discriminatingField(CMJ)).toBe("trial_id");
    const summary = rankMetric(CMJ, "cmj.jump_height_jhwd");
    expect(summary?.ranked.map((entry) => entry.entityId)).toEqual([
      "white-s000-t2",
      "white-s000-t1",
      "white-s000-t0",
    ]);
  });
});

describe("ranking", () => {
  it("orders served values descending and keeps each row's identity", () => {
    const summary = rankMetric(LOCOMOTOR, "locomotor.distance_total");
    expect(summary?.metricName).toBe("Total locomotor distance");
    expect(summary?.siUnit).toBe("m");
    expect(summary?.ranked.map((entry) => [entry.entityId, entry.value])).toEqual([
      ["p1", 10000],
      ["p2", 9000],
      ["p3", 8000],
    ]);
    // The served row travels with the bar, so a selection keeps its provenance.
    expect(summary?.ranked[0]?.derivedMetricId).toBe("dm-locomotor.distance_total-p1");
  });

  it("skips rows with no served value rather than plotting a zero", () => {
    const summary = rankMetric(
      [
        metric({ metric_id: "m", subject_id: "p1", value_num: 3 }),
        metric({ metric_id: "m", subject_id: "p2", value_num: null }),
      ],
      "m",
    );
    expect(summary?.ranked).toHaveLength(1);
  });
});

describe("zone breakdown", () => {
  it("places the served zone metrics side by side", () => {
    const zones = zoneBreakdown(LOCOMOTOR);
    expect(zones?.zones).toEqual(["low", "medium", "high"]);
    expect(zones?.entities).toEqual(["p1", "p2", "p3"]);
    expect(zones?.values[2]).toEqual([2000, 1200, 400]);
  });

  it("refuses a partial family rather than implying a missing zone is zero", () => {
    const partial = LOCOMOTOR.filter(
      (row) => row.metric_id !== "locomotor.distance_zone.high",
    );
    expect(zoneBreakdown(partial)).toBeNull();
  });
});

describe("leading fact", () => {
  it("attributes the largest value to the exact row that holds it", () => {
    const summary = rankMetric(LOCOMOTOR, "locomotor.distance_total");
    const fact = leadingFact(summary, (value, unit) => `${value} ${unit}`);
    expect(fact?.value).toBe("10000 m");
    expect(fact?.detail).toContain("p1");
    // "highest of N" states that this is a selection, not a computed statistic.
    expect(fact?.detail).toContain("highest of 3 served values");
    expect(fact?.derivedMetricId).toBe("dm-locomotor.distance_total-p1");
  });

  it("says nothing when there is nothing served to lead with", () => {
    expect(leadingFact(null, (value) => String(value))).toBeNull();
  });
});
