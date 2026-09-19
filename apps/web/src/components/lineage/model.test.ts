import { describe, expect, it } from "vitest";

import {
  detailRows,
  lineageLayer,
  toFlowElements,
} from "@/components/lineage/model";
import type { ProvenanceGraph } from "@/api/types";

const GRAPH: ProvenanceGraph = {
  derived_metric_id: "dm-1",
  nodes: [
    {
      id: "run:run-1",
      kind: "processing_run",
      label: "run-1",
      status: "completed",
      measurement_class: null,
      details: { code_git_sha: "b".repeat(40), started_at: "2026-09-18T12:00:00+00:00" },
    },
    {
      id: "dataset:demo",
      kind: "dataset",
      label: "Demo",
      status: null,
      measurement_class: null,
      details: { dataset_id: "demo" },
    },
    {
      id: "gold:dm-1",
      kind: "gold_row",
      label: "gold_trial_metrics · dm-1",
      status: null,
      measurement_class: "PIPELINE_DERIVED",
      details: { mart: "gold_trial_metrics" },
    },
  ],
  edges: [
    { id: "e1", source: "dataset:demo", target: "run:run-1", label: "input artifact" },
    { id: "e2", source: "run:run-1", target: "gold:dm-1", label: "results in" },
  ],
  provenance: { algorithm_id: "pose.test" },
  lineage_note: "Selected result lineage only.",
};

describe("lineage layout", () => {
  it("orders nodes deterministically by layer then id", () => {
    const first = toFlowElements(GRAPH);
    const second = toFlowElements(GRAPH);
    expect(first.nodes.map((node) => node.id)).toEqual(second.nodes.map((node) => node.id));
    expect(first.nodes.map((node) => node.id)).toEqual([
      "dataset:demo",
      "run:run-1",
      "gold:dm-1",
    ]);
    const xs = first.nodes.map((node) => node.position.x);
    const [firstX, secondX, thirdX] = xs;
    expect(firstX).toBeDefined();
    expect(secondX).toBeDefined();
    expect(thirdX).toBeDefined();
    expect(firstX as number).toBeLessThan(secondX as number);
    expect(secondX as number).toBeLessThan(thirdX as number);
  });

  it("maps every edge with its relationship label and preserves measurement class", () => {
    const { nodes, edges } = toFlowElements(GRAPH);
    expect(edges.map((edge) => edge.label)).toEqual(["input artifact", "results in"]);
    expect(edges[0]?.source).toBe("dataset:demo");
    const gold = nodes.find((node) => node.id === "gold:dm-1");
    expect(gold?.data.measurementClass).toBe("PIPELINE_DERIVED");
  });

  it("classifies unknown kinds without inventing a layer", () => {
    expect(lineageLayer("dataset")).toBe(0);
    expect(lineageLayer("gold_row")).toBe(6);
    expect(lineageLayer("mystery")).toBe(3);
  });
});

describe("lineage detail rows", () => {
  it("orders known identity keys first and drops empty values", () => {
    const rows = detailRows({
      zeta: 1,
      code_git_sha: "abc",
      dataset_id: "demo",
      empty: null,
      started_at: "2026-01-01T00:00:00Z",
    });
    expect(rows[0]).toEqual(["dataset_id", "demo"]);
    expect(rows[1]).toEqual(["code_git_sha", "abc"]);
    expect(rows.map(([key]) => key)).not.toContain("empty");
    expect(rows.map(([key]) => key)).toContain("started_at");
  });

  it("serializes structured details compactly", () => {
    expect(detailRows({ parameters: { a: 1 } })).toEqual([["parameters", '{"a":1}']]);
  });
});
