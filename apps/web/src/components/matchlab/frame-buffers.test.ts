import { describe, expect, it } from "vitest";

import {
  trackingEntityAt,
  trackingFrameIndexAt,
  trackingFrameSummaryAt,
  tacticalOverlayAtBuffers,
} from "@/components/matchlab/frame-buffers";
import { prepareTrackingWindow } from "@/lib/arrow/match-frame-preparation";
import type { DecodedWindow } from "@/lib/arrow/decode";

const decoded: DecodedWindow = {
  rowCount: 3,
  timeNs: new BigInt64Array([100n, 100n, 200n]),
  columns: [
    { name: "object_id", type: "Utf8", numeric: false, values: ["p2", "ball", "gk1"] },
    { name: "object_type", type: "Utf8", numeric: false, values: ["player", "ball", "goalkeeper"] },
    { name: "group_id", type: "Utf8", numeric: false, values: ["away", "", "home"] },
    { name: "x_m", type: "Float64", numeric: true, values: new Float64Array([3, 5, 1]) },
    { name: "y_m", type: "Float64", numeric: true, values: new Float64Array([4, 6, 2]) },
    { name: "is_detected", type: "Utf8", numeric: false, values: ["false", "true", "true"] },
  ],
};

describe("MatchLab tracking frame buffers", () => {
  it("keeps frame boundaries, identities, detection and provider types in typed columns", () => {
    const buffers = prepareTrackingWindow(decoded);

    expect([...buffers.frameTimesNs]).toEqual([100n, 200n]);
    expect([...buffers.frameOffsets]).toEqual([0, 2, 3]);
    expect(buffers.entityIds).toEqual(["ball", "gk1", "p2"]);
    expect([...buffers.objectKinds]).toEqual([2, 0, 1]);
    expect([...buffers.detectionState]).toEqual([1, 0, 1]);
    expect([...buffers.positionsXY]).toEqual([5, 6, 3, 4, 1, 2]);
    expect(trackingFrameSummaryAt(buffers, 0)).toMatchObject({ players: 1, extrapolated: 1, ballDetected: true });
    expect(trackingEntityAt(buffers, 0, "p2")).toMatchObject({ objectType: "player", xM: 3, yM: 4, detected: false });
  });

  it("draws tactical geometry at exact time and the latest bounded influence grid", () => {
    const emptyPolygons = {
      frameTimesNs: new BigInt64Array(),
      framePolygonOffsets: new Uint32Array([0]),
      polygonPointOffsets: new Uint32Array([0]),
      positionsXY: new Float32Array(),
      objectIds: [] as string[],
      objectIndexes: new Uint32Array(),
      groupIds: [] as string[],
      groupIndexes: new Int32Array(),
    };
    const influence = {
      gridTimesNs: new BigInt64Array([100n]),
      gridOffsets: new Uint32Array([0, 1]),
      positionsXY: new Float32Array([2, 3]),
      values: new Float32Array([1.5]),
      groupIds: ["home"],
      groupIndexes: new Int32Array([0]),
      cellWidthM: new Float32Array([5]),
      cellHeightM: new Float32Array([4]),
    };
    const overlay = tacticalOverlayAtBuffers({
      geometry: {
        frameTimesNs: new BigInt64Array([100n]),
        framePolygonOffsets: new Uint32Array([0, 1]),
        polygonPointOffsets: new Uint32Array([0, 3]),
        positionsXY: new Float32Array([0, 0, 1, 0, 1, 1]),
        objectIds: ["home"],
        objectIndexes: new Uint32Array([0]),
        groupIds: ["home"],
        groupIndexes: new Int32Array([0]),
      },
      territory: emptyPolygons,
      influence,
    }, 100n, () => "home", 50);

    expect(overlay.overlay.hulls).toHaveLength(1);
    expect(overlay.overlay.influenceCells).toMatchObject([{ xM: 2, yM: 3, arrivalTimeS: 1.5 }]);
    expect(overlay.influenceGridTimeNs).toBe(100n);
    expect(tacticalOverlayAtBuffers({ geometry: emptyPolygons, territory: emptyPolygons, influence }, 151n, () => "home", 50).overlay.influenceCells).toHaveLength(0);
  });

  it("resolves only a real source frame within the declared age tolerance", () => {
    const times = new BigInt64Array([100n, 200n, 300n]);
    expect(trackingFrameIndexAt(times, 250n, 100)).toBe(1);
    expect(trackingFrameIndexAt(times, 301n, 100)).toBe(2);
    expect(trackingFrameIndexAt(times, 301n, 0)).toBe(-1);
    expect(trackingFrameIndexAt(times, 50n, 100)).toBe(-1);
  });
});
