import { describe, expect, it } from "vitest";

import type { SessionDetail, SourceCapabilityView } from "@/api/types";
import { fileFamilies, formatBytes } from "@/components/catalog/PrepareDialog";
import { shortDatasetName } from "@/lib/catalog-model";
import { trialFacts } from "@/pages/performance";
import { verifiedParticipant } from "@/pages/player";

describe("preparation plan", () => {
  const entry = {
    provider_metadata: {
      file_families: {
        tracking: { key: "data/matches/1/1_tracking_extrapolated.jsonl", size_bytes: 90729279, upstream_revision: "4340d27" },
        match_metadata: { key: "data/matches/1/1_match.json", size_bytes: 33730, upstream_revision: "4340d27" },
        phases: { key: "data/matches/1/1_phases_of_play.csv", size_bytes: 115978, upstream_revision: "4340d27" },
      },
    },
    source_file_states: { tracking: "REGISTERED", match_metadata: "ACQUIRED" },
  } as unknown as SourceCapabilityView;

  it("lists declared files in a stable order with their live local state and exact bytes", () => {
    const files = fileFamilies(entry);
    expect(files.map((file) => file.family)).toEqual(["match_metadata", "tracking", "phases"]);
    expect(files.find((file) => file.family === "tracking")).toMatchObject({ sizeBytes: 90729279, state: "REGISTERED", revision: "4340d27" });
    expect(files.find((file) => file.family === "phases")?.state).toBe("UNKNOWN");
    expect(fileFamilies(null)).toEqual([]);
  });

  it("formats sizes in binary units and says when a size is unknown", () => {
    expect(formatBytes(33730)).toBe("32.9 KiB");
    expect(formatBytes(90729279)).toBe("86.5 MiB");
    expect(formatBytes(null)).toBe("size unknown");
  });
});

describe("readable identities", () => {
  it("shortens provider dataset titles without inventing names", () => {
    expect(shortDatasetName("White CMJ accelerometer + vGRF (preprocessed, Python format)")).toBe("White CMJ accelerometer + vGRF");
    expect(shortDatasetName("DFL/Sportec IDSSE — integrated tracking and event data")).toBe("DFL/Sportec IDSSE");
  });

  it("reads trial condition and index from provider trial labels", () => {
    expect(trialFacts({ trial_id: "white-s000-arms-t02", label: "condition=arms; source_row=165" })).toEqual({ condition: "arms", index: "02" });
    expect(trialFacts({ trial_id: "trial-x", label: null })).toEqual({ condition: null, index: null });
  });

  it("links a season player to a match participant only through the provider id crosswalk", () => {
    const session = {
      participants: [
        { subject_id: "133495", notes: "shirt 7 (C. Howieson)" },
        { subject_id: "10623", notes: "shirt 98 (V. Germain)" },
      ],
    } as unknown as SessionDetail;
    expect(verifiedParticipant(session, ["133495"])).toBe("133495");
    // A display-name match is never an identity.
    expect(verifiedParticipant(session, ["C. Howieson"])).toBeNull();
    expect(verifiedParticipant(undefined, ["133495"])).toBeNull();
  });
});
