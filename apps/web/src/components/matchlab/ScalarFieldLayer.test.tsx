import { describe, expect, it } from "vitest";
import ReactThreeTestRenderer from "@react-three/test-renderer";
import { InstancedMesh, LineSegments, Matrix4, Mesh } from "three";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import { useAnalysisStore } from "@/lib/state/analysis";

import { contourSegmentsForGrid, elevationHeightM, normalizeScalarValue, ScalarFieldLayer } from "@/components/matchlab/ScalarFieldLayer";
import type { ElevationSpec } from "@/components/matchlab/ScalarFieldLayer";
import type { TacticalGridWindowBuffers } from "@/components/matchlab/frame-buffers";

const ARRIVAL_TIME_ELEVATION: ElevationSpec = {
  metricId: "test.fixed_domain",
  measurementClass: "MODEL_ESTIMATED",
  scientificDomain: { min: 0, max: 5 },
  units: "s",
  elevationTransform: {
    kind: "linear-domain",
    direction: "decreasing",
    meaning: "Lower arrival time is shown higher.",
  },
  displayHeightLimitM: 2,
  baseline: { meaning: "pitch-plane-offset", offsetM: 0.016 },
  colorDomain: { min: 0, max: 5 },
  legendCopy: "Earlier arrival is higher.",
};

describe("fixed-domain scalar rendering", () => {
  it("saturates color values at the declared domain without changing the source value", () => {
    const domain = { min: 0, max: 5 };
    expect(normalizeScalarValue(-1, domain)).toBe(0);
    expect(normalizeScalarValue(2.5, domain)).toBe(0.5);
    expect(normalizeScalarValue(8, domain)).toBe(1);
    expect(domain).toEqual({ min: 0, max: 5 });
  });

  it("uses a metric-specific, inverted display transform with an explicit baseline", () => {
    expect(elevationHeightM(0, ARRIVAL_TIME_ELEVATION)).toBe(2);
    expect(elevationHeightM(2.5, ARRIVAL_TIME_ELEVATION)).toBe(1);
    expect(elevationHeightM(5, ARRIVAL_TIME_ELEVATION)).toBe(0);
    expect(ARRIVAL_TIME_ELEVATION.scientificDomain).toEqual({ min: 0, max: 5 });
  });

  it("builds an isoline from fixed levels on a regular grid", () => {
    const grid: TacticalGridWindowBuffers = {
      gridTimesNs: new BigInt64Array([1n]),
      gridOffsets: new Uint32Array([0, 4]),
      positionsXY: new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]),
      values: new Float32Array([0, 1, 0, 1]),
      groupIds: [],
      groupIndexes: new Int32Array([-1, -1, -1, -1]),
      cellWidthM: new Float32Array([1]),
      cellHeightM: new Float32Array([1]),
    };

    const segments = contourSegmentsForGrid(grid, 0, [0.5]);
    expect(segments).toHaveLength(6);
    expect(segments[0]).toBeCloseTo(0.5);
    expect(segments[1]).toBeCloseTo(0.018);
    expect(segments[2]).toBeCloseTo(0);
    expect(segments[3]).toBeCloseTo(0.5);
    expect(segments[4]).toBeCloseTo(0.018);
    expect(segments[5]).toBeCloseTo(-1);
  });

  it("renders a heatmap as instanced cells with the declared fixed-domain colors", async () => {
    const previous = useAnalysisStore.getState();
    useAnalysisStore.setState({ playheadNs: 1n, committedTimeNs: 1n });
    const matchFrame = {
      canonicalTimeNs: 1n,
      getCurrentTimeNs: () => 1n,
      selectTacticalObject: () => undefined,
      hoverTacticalObject: () => undefined,
    } as unknown as MatchFrameContextValue;
    try {
      const renderer = await ReactThreeTestRenderer.create(
        <ScalarFieldLayer
          buffers={{
            gridTimesNs: new BigInt64Array([1n]),
            gridOffsets: new Uint32Array([0, 2]),
            positionsXY: new Float32Array([0, 0, 1, 0]),
            values: new Float32Array([0, 10]),
            groupIds: [],
            groupIndexes: new Int32Array([-1, -1]),
            cellWidthM: new Float32Array([1]),
            cellHeightM: new Float32Array([1]),
          }}
          spec={{
            metricId: "test.fixed_domain",
            method: "test fixture",
            unit: "m",
            measurementClass: "MODEL_ESTIMATED",
            domain: { min: 0, max: 5 },
            mode: "heatmap",
          }}
          matchFrame={matchFrame}
        />,
      );
      await renderer.advanceFrames(1, 1 / 60);

      const meshNode = renderer.scene.find((node) => node.instance instanceof InstancedMesh);
      const mesh = meshNode.instance as InstancedMesh;
      expect(mesh.count).toBe(2);
      const matrix = new Matrix4();
      mesh.getMatrixAt(1, matrix);
      expect(matrix.elements[12]).toBeCloseTo(1);
      expect(matrix.elements[13]).toBeCloseTo(0.016);
      await renderer.unmount();
    } finally {
      useAnalysisStore.setState({
        playheadNs: previous.playheadNs,
        committedTimeNs: previous.committedTimeNs,
      });
    }
  });

  it("uses contour lines and a continuous display-only surface for analytical elevation", async () => {
    const previous = useAnalysisStore.getState();
    useAnalysisStore.setState({ playheadNs: 1n, committedTimeNs: 1n });
    const matchFrame = {
      canonicalTimeNs: 1n,
      getCurrentTimeNs: () => 1n,
      selectTacticalObject: () => undefined,
      hoverTacticalObject: () => undefined,
    } as unknown as MatchFrameContextValue;
    const buffers = {
      gridTimesNs: new BigInt64Array([1n]),
      gridOffsets: new Uint32Array([0, 4]),
      positionsXY: new Float32Array([0, 0, 1, 0, 0, 1, 1, 1]),
      values: new Float32Array([0, 5, 0, 5]),
      groupIds: [],
      groupIndexes: new Int32Array([-1, -1, -1, -1]),
      cellWidthM: new Float32Array([1]),
      cellHeightM: new Float32Array([1]),
    } satisfies TacticalGridWindowBuffers;

    try {
      const contour = await ReactThreeTestRenderer.create(
        <ScalarFieldLayer
          buffers={buffers}
          spec={{
            metricId: "test.fixed_domain",
            method: "test fixture",
            unit: "m",
            measurementClass: "PIPELINE_DERIVED",
            domain: { min: 0, max: 5 },
            mode: "contour",
            contourLevels: [2.5],
          }}
          matchFrame={matchFrame}
        />,
      );
      await contour.advanceFrames(1, 1 / 60);
      const lines = contour.scene.find((node) => node.instance instanceof LineSegments).instance as LineSegments;
      expect(lines.geometry.getAttribute("position").count).toBeGreaterThan(0);
      await contour.unmount();

      const elevation = await ReactThreeTestRenderer.create(
        <ScalarFieldLayer
          buffers={buffers}
          spec={{
            metricId: "test.fixed_domain",
            method: "test fixture",
            unit: "s",
            measurementClass: "MODEL_ESTIMATED",
            domain: { min: 0, max: 5 },
            mode: "elevation",
            elevationSpec: ARRIVAL_TIME_ELEVATION,
          }}
          matchFrame={matchFrame}
        />,
      );
      await elevation.advanceFrames(1, 1 / 60);
      const group = elevation.scene.find((node) => node.instance.name === "ScalarFieldLayer");
      const surface = elevation.scene.find((node) => node.instance instanceof Mesh && node.instance.geometry.getAttribute("position")?.count === 4).instance as Mesh;
      expect(group.instance.userData.displayOnlyElevation).toBe(true);
      expect(group.instance.userData.elevationSpec.legendCopy).toBe("Earlier arrival is higher.");
      expect(surface.geometry.getIndex()?.count).toBe(6);
      expect(surface.geometry.getAttribute("position").getY(0)).toBeCloseTo(2.016);
      expect(surface.geometry.getAttribute("position").getY(1)).toBeCloseTo(0.016);
      expect(buffers.values[0]).toBe(0);
      await elevation.unmount();
    } finally {
      useAnalysisStore.setState({
        playheadNs: previous.playheadNs,
        committedTimeNs: previous.committedTimeNs,
      });
    }
  });
});
