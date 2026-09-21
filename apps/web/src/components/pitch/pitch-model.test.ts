import { describe, expect, it } from "vitest";

import {
  assignGroups,
  buildFrames,
  DEFAULT_PITCH,
  entitiesAt,
  frameIndexAt,
  isTrackingStream,
  pitchToScreen,
  screenToPitch,
  summarizeFrame,
  trailForRange,
  type TrackingRow,
} from "@/components/pitch/pitch-model";

const ROWS: TrackingRow[] = [
  { t_rel_ns: 0, object_id: "ball", object_type: "ball", x_m: 0, y_m: 0, is_detected: true },
  {
    t_rel_ns: 0,
    object_id: "p1",
    object_type: "player",
    group_id: "team-b",
    x_m: -10,
    y_m: 5,
    is_detected: true,
  },
  {
    t_rel_ns: 0,
    object_id: "p2",
    object_type: "player",
    group_id: "team-a",
    x_m: 10,
    y_m: -5,
    is_detected: false,
  },
  { t_rel_ns: 40_000_000, object_id: "p1", object_type: "player", group_id: "team-b", x_m: -9.5, y_m: 5.5, is_detected: false },
  { t_rel_ns: 40_000_000, object_id: "ball", object_type: "ball", x_m: 0.5, y_m: 0.5, is_detected: false },
  { t_rel_ns: 80_000_000, object_id: "p1", object_type: "player", group_id: "team-b", x_m: null, y_m: 6 },
  { t_rel_ns: 80_000_000, object_id: "p2", object_type: "player", group_id: "team-a", x_m: 9, y_m: -5, is_detected: true },
];

describe("pitch geometry", () => {
  it("maps metres to pixels with an inverted Y axis and round-trips", () => {
    const viewport = { offsetX: 400, offsetY: 300, scale: 8 };
    const origin = pitchToScreen(0, 0, viewport);
    expect(origin).toEqual({ x: 400, y: 300 });
    const corner = pitchToScreen(DEFAULT_PITCH.lengthM / 2, DEFAULT_PITCH.widthM / 2, viewport);
    expect(corner.x).toBe(400 + (DEFAULT_PITCH.lengthM / 2) * 8);
    expect(corner.y).toBe(300 - (DEFAULT_PITCH.widthM / 2) * 8);
    const back = screenToPitch(corner.x, corner.y, viewport);
    expect(back.xM).toBeCloseTo(DEFAULT_PITCH.lengthM / 2, 9);
    expect(back.yM).toBeCloseTo(DEFAULT_PITCH.widthM / 2, 9);
  });

  it("recognizes tracking streams only", () => {
    expect(isTrackingStream("tracking")).toBe(true);
    expect(isTrackingStream("pose")).toBe(false);
    expect(isTrackingStream("event")).toBe(false);
  });
});

describe("frame indexing", () => {
  const frames = buildFrames(ROWS);

  it("groups rows by canonical time, sorts and drops unusable coordinates", () => {
    expect(frames.map((frame) => frame.tRelNs)).toEqual([0, 40_000_000, 80_000_000]);
    expect(frames[0]?.entities.map((entity) => entity.objectId)).toEqual(["ball", "p1", "p2"]);
    // p1's null-x row at 80 ms is dropped, never imputed.
    expect(frames[2]?.entities.map((entity) => entity.objectId)).toEqual(["p2"]);
  });

  it("finds the frame at or before a time and never extrapolates future frames", () => {
    expect(frameIndexAt(frames, 0n)).toBe(0);
    expect(frameIndexAt(frames, -1n)).toBe(-1);
    expect(frameIndexAt(frames, 39_999_999n)).toBe(0);
    expect(frameIndexAt(frames, 40_000_000n)).toBe(1);
    expect(frameIndexAt(frames, 10_000_000_000n)).toBe(2);
    expect(frameIndexAt([], 0n)).toBe(-1);
    expect(entitiesAt(frames, 40_000_000n).map((entity) => entity.objectId)).toEqual([
      "ball",
      "p1",
    ]);
  });

  it("summarizes detection without hiding extrapolation", () => {
    const summary = summarizeFrame(frames[1] ?? null);
    expect(summary).toEqual({
      tRelNs: 40_000_000,
      players: 1,
      extrapolated: 2,
      ballDetected: false,
    });
    expect(summarizeFrame(null)).toBeNull();
  });
});

describe("team assignment and trails", () => {
  const frames = buildFrames(ROWS);
  const groups = assignGroups(frames);

  it("assigns the two sorted provider groups deterministically", () => {
    expect(groups.get("p1")).toBe("away");
    expect(groups.get("p2")).toBe("home");
    expect(groups.get("ball")).toBe("ball");
  });

  it("scopes a trail to one entity and the committed range", () => {
    const full = trailForRange(frames, null, "p1");
    expect(full).toHaveLength(2);
    expect(full.map((point) => point.detected)).toEqual([true, false]);
    const scoped = trailForRange(
      frames,
      { fromNs: 40_000_000n, toNs: 80_000_000n },
      "p1",
    );
    expect(scoped).toHaveLength(1);
    expect(trailForRange(frames, null, null)).toEqual([]);
  });
});
