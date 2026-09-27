import { describe, expect, it } from "vitest";

import type { SeasonMetricView, SeasonProfileView, SeasonRankedMetricView } from "@/api/types";
import {
  buildSeasonReport,
  formatSeasonValue,
  groupMetrics,
  parseMetricList,
  rangePosition,
  resolveSelectedMetrics,
  shortTeamName,
  splitCounterparts,
  splitPairs,
} from "@/lib/season-model";

function metric(column: string, extra: Partial<SeasonMetricView> = {}): SeasonMetricView {
  return {
    metric_id: `skillcorner.physical.${column}`,
    column,
    family: "physical",
    label: column,
    group: "Volume",
    unit: "m",
    basis: "per match (season mean)",
    definition: column,
    split: null,
    base: null,
    exposure: false,
    higher_is: "more",
    ...extra,
  };
}

const REGISTRY: SeasonMetricView[] = [
  metric("total_distance_full_all", { split: "all", base: "total_distance", label: "Total distance" }),
  metric("total_distance_full_tip", { split: "tip", base: "total_distance" }),
  metric("total_distance_full_otip", { split: "otip", base: "total_distance" }),
  metric("psv99", { unit: "km/h", group: "Peak speed" }),
  metric("count_match", { unit: "matches", group: "Exposure", exposure: true }),
];

function ranked(column: string, value: number | null): SeasonRankedMetricView {
  return {
    metric_id: `skillcorner.physical.${column}`,
    column,
    value,
    rank: value === null ? null : 3,
    percentile: value === null ? null : 72.5,
    valid_n: 40,
    population_minimum: 0,
    population_median: 50,
    population_maximum: 100,
  };
}

describe("season model", () => {
  it("keeps only registered metrics and falls back to the family default panel", () => {
    expect(parseMetricList("psv99, psv99,,count_match")).toEqual(["psv99", "count_match"]);
    expect(resolveSelectedMetrics("physical", "psv99,unknown", REGISTRY)).toEqual(["psv99"]);
    // Default panel filtered to what this registry defines.
    expect(resolveSelectedMetrics("physical", undefined, REGISTRY)).toEqual([
      "total_distance_full_all",
      "psv99",
    ]);
  });

  it("requests TIP/OTIP counterparts inside the same profile query", () => {
    expect(splitCounterparts(["total_distance_full_all", "psv99"], REGISTRY)).toEqual([
      "total_distance_full_tip",
      "total_distance_full_otip",
    ]);
    const pairs = splitPairs(["total_distance_full_all"], REGISTRY, [
      ranked("total_distance_full_tip", 3000),
      ranked("total_distance_full_otip", 4000),
    ]);
    expect(pairs).toHaveLength(1);
    expect(pairs[0]!.tip?.value).toBe(3000);
    expect(pairs[0]!.otip?.value).toBe(4000);
  });

  it("orders exposure groups last", () => {
    expect(groupMetrics(REGISTRY).map((group) => group.group)).toEqual(["Volume", "Peak speed", "Exposure"]);
  });

  it("formats by unit and positions values inside the population range", () => {
    expect(formatSeasonValue(10515.04, "m")).toBe("10,515");
    expect(formatSeasonValue(28.83, "km/h")).toBe("28.83");
    expect(formatSeasonValue(null, "m")).toBe("—");
    expect(rangePosition(75, 50, 100)).toBe(0.5);
    expect(rangePosition(10, 10, 10)).toBe(0.5);
    expect(rangePosition(null, 0, 1)).toBeNull();
    expect(shortTeamName("Perth Glory Football Club")).toBe("Perth Glory");
    expect(shortTeamName("Melbourne City FC")).toBe("Melbourne City");
  });

  it("builds a reproducible report naming denominator, provenance and rights", () => {
    const profile: SeasonProfileView = {
      edition: {
        dataset_id: "skillcorner-opendata",
        provider: "SkillCorner / PySport",
        sport_id: "football",
        sport_name: "Football",
        competition_id: "c",
        competition_name: "A-League",
        edition_id: "e",
        edition_label: "2024/2025",
        measurement_class: "SOURCE_DERIVED",
        inclusion_rule: "performances above 60 minutes",
        glossary_url: null,
        registry_version: "skillcorner-season-metrics/1",
        license: {
          policy_id: "p",
          identifier: "MIT",
          status: "declared",
          attribution_required: true,
          noncommercial_only: false,
          share_alike: false,
          redistribution: "conditional",
          local_only: false,
          restrictions: [],
          notice: "MIT; attribution required",
        },
        families: [],
      },
      family: {
        family: "physical",
        label: "Physical",
        artifact_id: "artifact-1",
        row_count: 406,
        checksum_sha256: "abc123",
        run_id: "run-9",
        grain_kind: "PLAYER_SEASON",
        grain_axes: ["subject", "team"],
        source_revision: "rev",
        source_file_key: "file.csv",
        source_population_rows: 406,
        match_count_column: "count_match",
      },
      row: {
        subject_id: "s/1",
        player_name: "Adam Taggart",
        player_short_name: "A. Taggart",
        team_id: "t",
        team_name: "Perth Glory Football Club",
        position_group: "Center Forward",
        matches: 24,
        values: { psv99: 28.83 },
      },
      population: {
        scope: "position",
        label: "Center Forward rows, A-League 2024/2025",
        team_id: null,
        position_group: "Center Forward",
        min_matches: null,
        rows: 74,
        unit_of_analysis: "player × team × position-group season row",
        selected_row_in_population: true,
      },
      metrics: [ranked("psv99", 28.83)],
      percentile_method: "inclusive",
      rank_method: "rank 1 = largest",
      caveats: ["descriptive only"],
    };
    const report = buildSeasonReport({ profile, registry: REGISTRY, url: "http://x/season?edition=e" });
    expect(report).toContain("# Season profile — Adam Taggart");
    expect(report).toContain("Population: Center Forward rows, A-League 2024/2025");
    expect(report).toContain("Rows: 74");
    expect(report).toContain("| psv99 | per match (season mean) | 28.83 km/h | 3/40 | P73 | 40 |");
    expect(report).toContain("`artifact-1` sha256 `abc123`");
    expect(report).toContain("MIT; attribution required");
    expect(report).toContain("Reproduce: http://x/season?edition=e");
  });
});
