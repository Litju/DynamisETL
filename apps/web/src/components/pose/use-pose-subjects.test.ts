import { describe, expect, it } from "vitest";

import { firstPoseObservationInRange, poseSubjectObservations } from "@/components/pose/use-pose-subjects";

describe("Pose observation authority", () => {
  const artifact = {
    entity_observations: [
      {
        entity_id: "560986",
        first_observed_ns: 12_000_000_000,
        last_observed_ns: 20_000_000_000,
        observation_count: 200,
      },
    ],
  } as never;

  it("keeps numeric subject ids and first observation time exact", () => {
    const [observation] = poseSubjectObservations(artifact);
    expect(observation?.entityId).toBe("560986");
    expect(firstPoseObservationInRange(observation, null, null)).toBe(12_000_000_000n);
  });

  it("returns no target when the authoritative bounds do not overlap a range", () => {
    const [observation] = poseSubjectObservations(artifact);
    expect(firstPoseObservationInRange(observation, 0n, 10_000_000_000n)).toBeNull();
  });
});
