import { describe, expect, it } from "vitest";

import type { ArtifactRef, TacticalCapabilityView } from "@/api/types";
import {
  bucketBounds,
  byTeam,
  liveReadWindow,
  levelStatus,
  reportPayload,
  rowsAtFrame,
} from "@/components/shell/tactical-pane-model";

const CAPABILITY = {
  dataset_id: "skillcorner-opendata",
  accepted_slice: {},
  semantics: {},
  capabilities: {
    level_a_geometry: "supported_with_model_input_quality",
    level_b_territory: "supported_with_model_input_quality",
    level_c_influence: "supported_partial_with_model_input_quality",
    level_d_event_linked: "unavailable",
    level_e_shape_phase: "unavailable",
    matchlab_v3_functional_units: "supported_from_declared_roles",
  },
  quality_evidence: {},
  unavailable_reasons: [
    "no accepted local event or phase artifact",
    "attacking-direction semantics are not declared",
  ],
} as unknown as TacticalCapabilityView;

function artifact(level: string, series: string): ArtifactRef {
  return {
    artifact_id: `proc-${series}`,
    checksum_sha256: "a".repeat(64),
    run_id: `run-${level}`,
    algorithm_id: `tactical.${level}`,
    algorithm_version: "1",
    parameters_hash: "b".repeat(64),
    measurement_class: level === "C" ? "MODEL_ESTIMATED" : "PIPELINE_DERIVED",
    artifact_metadata: { tactical_level: level, series_name: series },
  } as unknown as ArtifactRef;
}

describe("levelStatus (RES-112 T-01)", () => {
  it("separates unsupported, not materialized and available", () => {
    const artifacts = [artifact("A", "team_geometry")];
    expect(levelStatus("A", CAPABILITY, artifacts).kind).toBe("available");
    expect(levelStatus("C", CAPABILITY, artifacts)).toEqual({
      kind: "not_materialized",
      capability: "supported_partial_with_model_input_quality",
      algorithmId: "tactical.arrival_time",
    });
    const events = levelStatus("D", CAPABILITY, artifacts);
    expect(events.kind).toBe("unsupported");
    expect(events.kind === "unsupported" && events.reasons).toEqual(["no accepted local event or phase artifact"]);
    expect(levelStatus("E", CAPABILITY, artifacts).kind).toBe("unsupported");
  });
});

describe("current-frame helpers", () => {
  it("aligns live windows to fixed buckets so the key changes once per bucket", () => {
    expect(bucketBounds(45_000_000_000n, 30_000_000_000n)).toEqual({ fromNs: 30_000_000_000n, toNs: 59_999_999_999n });
    expect(bucketBounds(59_999_999_999n, 30_000_000_000n).fromNs).toBe(30_000_000_000n);
  });

  it("reads back across a bucket boundary so the drawn frame is always included", () => {
    // DFL frames sit on a 40 ms grid from 1.02 s: at 300.000 s the drawn frame
    // is 299.980 s, which belongs to the previous 30 s bucket.
    const window = liveReadWindow(300_000_000_000n, 30_000_000_000n, 2_000_000_000n);
    expect(window.fromNs).toBeLessThanOrEqual(299_980_000_000n);
    expect(window.toNs).toBe(329_999_999_999n);
  });

  it("returns one row per team at the playhead frame only (T-03/T-04)", () => {
    const rows = [
      { t_rel_ns: 0, group_id: "B", width_m: 1 },
      { t_rel_ns: 0, group_id: "A", width_m: 2 },
      { t_rel_ns: 100, group_id: "B", width_m: 3 },
      { t_rel_ns: 100, group_id: "A", width_m: 4 },
    ];
    const current = byTeam(rowsAtFrame(rows, 120n, 150), ["A", "B"]);
    expect(current.map(({ groupId, row }) => [groupId, row["width_m"]])).toEqual([["A", 4], ["B", 3]]);
    expect(rowsAtFrame(rows, 400n, 150)).toEqual([]);
    expect(rowsAtFrame(rows, null, 150)).toEqual([]);
  });
});

describe("reportPayload (T-08)", () => {
  it("carries artifact and run provenance per level and no conclusions", () => {
    const artifacts = [artifact("A", "team_geometry")];
    const statuses = {
      A: levelStatus("A", CAPABILITY, artifacts),
      B: levelStatus("B", CAPABILITY, artifacts),
      C: levelStatus("C", CAPABILITY, artifacts),
      D: levelStatus("D", CAPABILITY, artifacts),
      E: levelStatus("E", CAPABILITY, artifacts),
      V3: levelStatus("V3", CAPABILITY, artifacts),
    };
    const payload = reportPayload({
      datasetId: "skillcorner-opendata",
      sessionId: "1925299",
      streamId: "tracking-period-1",
      timeNs: 5n,
      range: null,
      capability: CAPABILITY,
      statuses,
      teamLabels: new Map([["871", "Perth Glory Football Club"]]),
      rangeTeamRows: 0,
      eventRows: 0,
    });
    const levels = payload.levels as Record<string, Record<string, unknown>>;
    expect(levels.A!.status).toBe("available");
    expect((levels.A!.artifacts as Array<Record<string, unknown>>)[0]).toMatchObject({ run_id: "run-A", series_name: "team_geometry" });
    expect(levels.C!.status).toBe("not_materialized");
    expect(levels.D!.status).toBe("unsupported");
    expect(payload.time_ns).toBe("5");
    expect(payload.conclusion_policy).toMatch(/quantitative summary only/);
  });
});
