import { describe, expect, it } from "vitest";

import { buildUPlotData } from "@/components/charts/uplot-data";

describe("buildUPlotData", () => {
  it("passes explicit null gaps to uPlot for traces and reduction bands", () => {
    const result = buildUPlotData(
      [{ id: "force", label: "Force", unit: "N" }],
      [
        {
          name: "Force",
          unit: "N",
          measurementClass: "RAW_MEASURED",
          paneIndex: 0,
          points: [[0, 1], [1, null], [2, 3]],
        },
      ],
      [
        {
          name: "Force",
          base: "force",
          unit: "N",
          measurementClass: "RAW_MEASURED",
          paneIndex: 0,
          points: [[0, 0, 2], [1, null, null], [2, 2, 4]],
        },
      ],
    );

    expect(result.data[0]).toEqual([0, 1, 2]);
    expect(result.data[1]).toEqual([1, null, 3]);
    expect(result.data[2]).toEqual([0, null, 2]);
    expect(result.data[3]).toEqual([2, null, 4]);
    expect(result.data).toHaveLength(4);
    expect(result.bands).toEqual([{ series: [2, 3], fill: expect.any(String) }]);
  });
});
