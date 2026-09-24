import { describe, expect, it } from "vitest";

import type { StreamView } from "@/api/types";
import { canonicalPlayerIdForTracking, streamsForPeriod } from "@/lib/match-frame-context";

function stream(streamId: string, modality: string, trialId: string): StreamView {
  return {
    stream_id: streamId,
    modality,
    trial_id: trialId,
    sample_artifact_ids: [],
  } as unknown as StreamView;
}

describe("MatchFrameContext identity and period resolution", () => {
  it("pairs tracking and Pose only within the same period", () => {
    const streams = [
      stream("tracking-p1", "tracking", "period-1"),
      stream("pose-p1", "pose", "period-1"),
      stream("tracking-p2", "tracking", "period-2"),
      stream("pose-p2", "pose", "period-2"),
    ];

    expect(streamsForPeriod(streams, "period-2")).toEqual({
      tracking: streams[2],
      pose: streams[3],
    });
    expect(streamsForPeriod(streams, null)).toEqual({ tracking: null, pose: null });
  });

  it("maps only registered player and goalkeeper objects to player identity", () => {
    const participants = new Set(["p1", "gk1"]);

    expect(canonicalPlayerIdForTracking("p1", "player", participants)).toBe("p1");
    expect(canonicalPlayerIdForTracking("gk1", "goalkeeper", participants)).toBe("gk1");
    expect(canonicalPlayerIdForTracking("ball", "ball", participants)).toBeNull();
    expect(canonicalPlayerIdForTracking("unknown", "player", participants)).toBeNull();
  });
});
