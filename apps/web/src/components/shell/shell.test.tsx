import { describe, expect, it } from "vitest";

import { filterCommands, type Command } from "@/components/command/CommandPalette";
import { contextSegments } from "@/components/shell/ContextBar";
import { qualityRibbonText, summarizeQuality } from "@/components/shell/Transport";

const COMMANDS: Command[] = [
  { id: "a", title: "Go to Catalog", group: "Navigate", run: () => undefined },
  { id: "b", title: "Play/pause playback", group: "Transport", run: () => undefined },
  { id: "c", title: "Switch to Report Light", group: "View", run: () => undefined },
];

describe("command palette filtering", () => {
  it("matches by title or group, case-insensitively", () => {
    expect(filterCommands(COMMANDS, "catalog").map((c) => c.id)).toEqual(["a"]);
    expect(filterCommands(COMMANDS, "transport").map((c) => c.id)).toEqual(["b"]);
    expect(filterCommands(COMMANDS, "light").map((c) => c.id)).toEqual(["c"]);
    expect(filterCommands(COMMANDS, "  ").map((c) => c.id)).toEqual(["a", "b", "c"]);
    expect(filterCommands(COMMANDS, "nothing")).toEqual([]);
  });
});

describe("context bar segments", () => {
  it("shows the durable laboratory context from the URL", () => {
    const segments = contextSegments(
      "/lab/skillcorner-opendata/1925299",
      "?trial=period-1&subject=809166&metric=pose.angular_rom.left_knee",
    );
    expect(segments).toEqual([
      { label: "dataset", value: "skillcorner-opendata", mono: true },
      { label: "session", value: "1925299", mono: true },
      { label: "trial", value: "period-1", mono: true },
      { label: "subject", value: "809166", mono: false },
      { label: "metric", value: "pose.angular_rom.left_knee", mono: true },
    ]);
  });

  it("labels non-laboratory surfaces without inventing context", () => {
    expect(contextSegments("/quality", "")).toEqual([{ label: "surface", value: "quality" }]);
    expect(contextSegments("/", "")).toEqual([]);
  });
});

describe("quality ribbon", () => {
  it("counts quarantine and warnings without hiding either", () => {
    const summary = summarizeQuality([
      { severity: "ERROR", state: "VALID" },
      { severity: "WARNING", state: "QUARANTINED" },
      { severity: "WARNING", state: "VALID" },
      { severity: "INFO", state: "VALID" },
    ] as Parameters<typeof summarizeQuality>[0]);
    expect(summary).toEqual({ quarantined: 2, warnings: 1, infos: 1 });
    expect(qualityRibbonText(summary)).toBe("2 quarantined · 1 warning · 1 info");
  });

  it("states absence and unavailability explicitly", () => {
    expect(qualityRibbonText({ quarantined: 0, warnings: 0, infos: 0 })).toBe(
      "no flagged intervals in the current selection",
    );
    expect(qualityRibbonText(null)).toBe("quality context unavailable");
  });
});
