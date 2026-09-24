import { describe, expect, it } from "vitest";

import { buildFrames } from "@/components/pitch/pitch-model";
import { trackingBuffersFromFrames, trackingFrameIndexAt } from "@/components/matchlab/frame-buffers";

describe("MatchLab tracking frame buffers", () => {
  it("keeps frame boundaries, identities, detection and provider types in typed columns", () => {
    const frames = buildFrames([
      { t_rel_ns: 100, object_id: "p2", object_type: "player", group_id: "away", x_m: 3, y_m: 4, is_detected: false },
      { t_rel_ns: 100, object_id: "ball", object_type: "ball", group_id: null, x_m: 5, y_m: 6, is_detected: true },
      { t_rel_ns: 200, object_id: "gk1", object_type: "goalkeeper", group_id: "home", x_m: 1, y_m: 2, is_detected: true },
    ]);
    const buffers = trackingBuffersFromFrames(frames);

    expect([...buffers.frameTimesNs]).toEqual([100n, 200n]);
    expect([...buffers.frameOffsets]).toEqual([0, 2, 3]);
    expect(buffers.entityIds).toEqual(["ball", "gk1", "p2"]);
    expect([...buffers.objectKinds]).toEqual([2, 0, 1]);
    expect([...buffers.detectionState]).toEqual([1, 0, 1]);
    expect([...buffers.positionsXY]).toEqual([5, 6, 3, 4, 1, 2]);
  });

  it("resolves only a real source frame within the declared age tolerance", () => {
    const times = new BigInt64Array([100n, 200n, 300n]);
    expect(trackingFrameIndexAt(times, 250n, 100)).toBe(1);
    expect(trackingFrameIndexAt(times, 301n, 100)).toBe(2);
    expect(trackingFrameIndexAt(times, 301n, 0)).toBe(-1);
    expect(trackingFrameIndexAt(times, 50n, 100)).toBe(-1);
  });
});
