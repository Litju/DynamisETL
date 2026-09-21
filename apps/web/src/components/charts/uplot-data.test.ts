import { describe, expect, it } from "vitest";

import { buildUPlotData } from "@/components/charts/uplot-data";

describe("buildUPlotData", () => {
  it("keeps aligned gaps and reduction bands in typed columns", () => {
    const result = buildUPlotData(
      [{ id: "force", label: "Force", unit: "N" }],
      [
        {
          name: "Force",
          unit: "N",
          measurementClass: "RAW_MEASURED",
          paneIndex: 0,
          points: [[0, 1], [1, null]],
        },
      ],
      [
        {
          name: "Force",
          base: "force",
          unit: "N",
          measurementClass: "RAW_MEASURED",
          paneIndex: 0,
          points: [[0, 0, 2], [1, null, null]],
        },
      ],
    );

    expect(result.data[0]).toBeInstanceOf(Float64Array);
    expect(Number.isNaN(result.data[1]![1]!)).toBe(true);
    expect(result.data).toHaveLength(4);
    expect(result.bands).toEqual([{ series: [2, 3], fill: expect.any(String) }]);
  });
});
