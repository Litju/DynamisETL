import { describe, expect, it } from "vitest";

import { compactParticipantLabel } from "@/lib/participants";

describe("compactParticipantLabel", () => {
  it("reorders the registered football note and keeps other notes", () => {
    expect(compactParticipantLabel("shirt 16 (Christopher Schindler)")).toBe("Christopher Schindler #16");
    expect(compactParticipantLabel("dataset-scoped participant identity")).toBe("dataset-scoped participant identity");
    expect(compactParticipantLabel(null)).toBeNull();
  });
});
