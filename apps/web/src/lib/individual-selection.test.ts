import { describe, expect, it } from "vitest";

import type { ArtifactDetail, StreamView } from "@/api/types";
import { resolveSignalStream, stableIndividualIds } from "@/lib/individual-selection";

function stream(
  streamId: string,
  subjectId: string | null,
  trialId = "trial-1",
): StreamView {
  return {
    stream_id: streamId,
    modality: "force",
    measurement_class: "RAW_MEASURED",
    subject_id: subjectId,
    trial_id: trialId,
    device_id: null,
    nominal_sampling_rate_hz: 100,
    si_units: ["N"],
    source_unit: "N",
    coordinate_frame_id: null,
    synchronization_spec_id: "sync",
    clock_id: "clock",
    skeleton_id: null,
    sample_artifact_ids: [`artifact-${streamId}`],
    sample_row_count: 1,
  };
}

describe("stable individual selection", () => {
  it("uses artifact identities instead of the current window", () => {
    const artifact: Pick<ArtifactDetail, "entity_ids"> = { entity_ids: ["s2", "s1"] };
    expect(stableIndividualIds(artifact, [])).toEqual(["s1", "s2"]);
  });

  it("resolves the selected subject to the compatible real trial stream", () => {
    const current = stream("force-s1", "s1");
    const selected = resolveSignalStream(
      [current, stream("force-s2-later", "s2", "trial-2"), stream("force-s2", "s2")],
      current,
      "s2",
    );
    expect(selected?.stream_id).toBe("force-s2");
  });

  it("does not fall back to another subject when no compatible stream exists", () => {
    const current = stream("force-s1", "s1");
    expect(resolveSignalStream([current], current, "s2")).toBeNull();
  });
});
