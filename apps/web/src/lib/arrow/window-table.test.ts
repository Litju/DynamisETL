import { describe, expect, it } from "vitest";

import {
  bandPairs,
  bandPointsFor,
  entityKeys,
  measureColumns,
  originNs,
  pointsFor,
  tableFromJson,
} from "@/lib/arrow/window-table";
import type { DenseWindow } from "@/api/types";

const ARTIFACT = {
  artifact_id: "a1",
  dataset_id: "demo",
  stream_id: "s1",
  layer: "silver",
  relative_path: "silver/demo/x.parquet",
  format: "parquet",
  compression: "zstd",
  checksum_sha256: "a".repeat(64),
  row_count: 3,
  byte_size: 10,
  artifact_kind: "sample" as const,
  modality: "tracking",
  measurement_class: "MODEL_ESTIMATED",
  si_units: ["m"],
  coordinate_frame_id: "frame",
  synchronization_spec_id: "sync",
};

function windowOf(rows: Array<Record<string, unknown>>, columns: string[]): DenseWindow {
  return {
    meta: {
      artifact: ARTIFACT,
      from_ns: 0,
      to_ns: 100,
      columns,
      source_rows: rows.length,
      returned_rows: rows.length,
      canonical_time_min_ns: 0,
      canonical_time_max_ns: 100,
      reduction: null,
      units: { x_m: "m" },
      coordinate_frame_id: "frame",
      measurement_class: "MODEL_ESTIMATED",
      display_note: "Exact.",
    },
    rows,
  };
}

describe("window table from JSON fallback", () => {
  const table = tableFromJson(
    windowOf(
      [
        { t_rel_ns: 0, subject_id: "b", x_m: 0, is_detected: true },
        { t_rel_ns: 10, subject_id: "a", x_m: 1.5, is_detected: false },
        { t_rel_ns: 20, subject_id: "b", x_m: null, is_detected: true },
      ],
      ["t_rel_ns", "subject_id", "x_m", "is_detected"],
    ),
  );

  it("keeps columnar typed arrays and exact time", () => {
    expect(table.rowCount).toBe(3);
    expect(Array.from(table.timeNs)).toEqual([0n, 10n, 20n]);
    expect(Array.from(table.numeric.get("x_m") ?? [])).toEqual([0, 1.5, Number.NaN]);
    expect(table.strings.get("subject_id")).toEqual(["b", "a", "b"]);
    expect(originNs(table)).toBe(0n);
  });

  it("selects measures and groups entity rows deterministically", () => {
    expect(measureColumns(table)).toEqual(["x_m"]);
    const groups = entityKeys(table);
    expect(groups.map((group) => group.id)).toEqual(["a", "b"]);
    expect(groups[1]?.rows).toEqual([0, 2]);
    const points = pointsFor(table, "x_m", groups[1]?.rows ?? [], originNs(table));
    expect(points).toEqual([
      [0, 0],
      [0.00002, null],
    ]);
  });

  it("shapes reduced envelope pairs", () => {
    const reduced = tableFromJson(
      windowOf(
        [
          { t_rel_ns: 0, x_m_min: 0, x_m_max: 2 },
          { t_rel_ns: 10, x_m_min: 1, x_m_max: 3 },
        ],
        ["t_rel_ns", "x_m_min", "x_m_max"],
      ),
    );
    expect(bandPairs(reduced)).toEqual([
      { base: "x_m", minKey: "x_m_min", maxKey: "x_m_max" },
    ]);
    expect(measureColumns(reduced)).toEqual([]);
    expect(bandPointsFor(reduced, "x_m_min", "x_m_max", 0n)).toEqual([
      [0, 0, 2],
      [0.00001, 1, 3],
    ]);
  });

  it("infers numeric columns after leading null gaps", () => {
    const leadingGap = tableFromJson(
      windowOf(
        [
          { t_rel_ns: 0, x_m: null },
          { t_rel_ns: 10, x_m: 1.5 },
        ],
        ["t_rel_ns", "x_m"],
      ),
    );
    expect(measureColumns(leadingGap)).toEqual(["x_m"]);
    expect(Array.from(leadingGap.numeric.get("x_m") ?? [])).toEqual([Number.NaN, 1.5]);
  });
});
