import { describe, expect, it } from "vitest";

import { buildPitchMarkingPositions } from "@/components/matchlab/Pitch3D";

function coordinateBounds(positions: Float32Array, component: 0 | 2) {
  const values = Array.from({ length: positions.length / 3 }, (_, index) => positions[index * 3 + component]!);
  return { min: Math.min(...values), max: Math.max(...values) };
}

describe("Pitch3D source geometry", () => {
  it("uses the registered pitch dimensions for the touchline and goal-line extents", () => {
    const positions = buildPitchMarkingPositions({ lengthM: 105, widthM: 68 });
    const x = coordinateBounds(positions, 0);
    const z = coordinateBounds(positions, 2);

    expect(positions.length).toBeGreaterThan(0);
    expect(x.min).toBeCloseTo(-52.55);
    expect(x.max).toBeCloseTo(52.55);
    expect(z.min).toBeCloseTo(-34.05);
    expect(z.max).toBeCloseTo(34.05);
  });

  it("rejects missing or invalid metric pitch dimensions", () => {
    expect(() => buildPitchMarkingPositions({ lengthM: Number.NaN, widthM: 68 })).toThrow(RangeError);
    expect(() => buildPitchMarkingPositions({ lengthM: 105, widthM: 0 })).toThrow(RangeError);
  });
});
