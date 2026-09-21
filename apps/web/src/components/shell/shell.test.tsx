import { describe, expect, it } from "vitest";

import { filterCommands, type Command } from "@/components/command/CommandPalette";
import { contextCrumbs } from "@/components/shell/ContextBar";
import { shellLayoutFor } from "@/components/shell/AppShell";
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

describe("context spine", () => {
  it("reads human-readable names first and keeps the exact id as evidence", () => {
    const crumbs = contextCrumbs(
      "/lab/skillcorner-opendata/1925299",
      "?trial=period_1&subject=809166",
      { dataset: "SkillCorner Open Data", session: "Brisbane Roar FC 0-1 Perth Glory" },
    );
    expect(crumbs.map((crumb) => [crumb.label, crumb.id])).toEqual([
      ["Laboratory", undefined],
      ["SkillCorner Open Data", "skillcorner-opendata"],
      ["Brisbane Roar FC 0-1 Perth Glory", "1925299"],
      ["period_1", "period_1"],
      ["Subject 809166", "809166"],
    ]);
  });

  it("falls back to the identifier when no readable name is resolved yet", () => {
    const crumbs = contextCrumbs("/lab/white-cmj-acc-grf/white-s000", "");
    expect(crumbs.map((crumb) => crumb.label)).toEqual([
      "Laboratory",
      "white-cmj-acc-grf",
      "white-s000",
    ]);
  });

  it("labels non-laboratory surfaces without inventing context", () => {
    expect(contextCrumbs("/quality", "")).toEqual([
      { key: "surface", label: "Quality & rights", to: "/quality" },
    ]);
    expect(contextCrumbs("/", "")).toEqual([]);
  });
});

describe("shell layout", () => {
  it("grants the explorer, inspector and transport only inside a laboratory session", () => {
    expect(shellLayoutFor("/lab/skillcorner-opendata/1925299")).toEqual({
      explorer: true,
      inspector: true,
      transport: true,
    });
  });

  it("keeps empty panes off surfaces that own their own evidence", () => {
    for (const pathname of ["/catalog", "/compare", "/methods", "/runs", "/quality", "/lab"]) {
      expect(shellLayoutFor(pathname)).toEqual({
        explorer: false,
        inspector: false,
        transport: false,
      });
    }
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
