import { describe, expect, it } from "vitest";

import { filterCommands, type Command } from "@/components/command/CommandPalette";
import { shellLayoutFor } from "@/components/shell/AppShell";
import { qualityRibbonText, summarizeQuality } from "@/components/shell/Transport";
import { useShellContext } from "@/lib/state/context";
import { lastContextOf, relativeTime, useRecentContexts } from "@/lib/state/recent";

const COMMANDS: Command[] = [
  { id: "a", title: "Go to Library", group: "Navigate", run: () => undefined },
  { id: "b", title: "Play/pause playback", group: "Transport", run: () => undefined },
  { id: "c", title: "Switch to Report Light", group: "View", run: () => undefined },
];

describe("command palette filtering", () => {
  it("matches by title or group, case-insensitively", () => {
    expect(filterCommands(COMMANDS, "library").map((c) => c.id)).toEqual(["a"]);
    expect(filterCommands(COMMANDS, "transport").map((c) => c.id)).toEqual(["b"]);
    expect(filterCommands(COMMANDS, "light").map((c) => c.id)).toEqual(["c"]);
    expect(filterCommands(COMMANDS, "  ").map((c) => c.id)).toEqual(["a", "b", "c"]);
    expect(filterCommands(COMMANDS, "nothing")).toEqual([]);
  });
});

describe("context spine", () => {
  it("publishes readable crumbs and ignores retraction by a previous owner", () => {
    const store = useShellContext.getState();
    store.publish({ owner: "match:a/1", world: "match", crumbs: [{ key: "match", label: "Auckland FC 2–1 Macarthur FC" }] });
    expect(useShellContext.getState().context?.crumbs[0]?.label).toBe("Auckland FC 2–1 Macarthur FC");
    // The next World publishes before the previous screen unmounts; the late
    // retraction of the old owner must not blank the new context.
    store.publish({ owner: "game:e:g", world: "game", crumbs: [{ key: "game", label: "Game", pending: true }] });
    store.retract("match:a/1");
    expect(useShellContext.getState().context?.owner).toBe("game:e:g");
    expect(useShellContext.getState().context?.crumbs[0]?.pending).toBe(true);
    store.retract("game:e:g");
    expect(useShellContext.getState().context).toBeNull();
  });
});

describe("recent contexts", () => {
  it("keeps one entry per context, newest first, as exact URLs", () => {
    const { record, clear } = useRecentContexts.getState();
    clear();
    record({ key: "match:a/1", world: "match", title: "A", subtitle: "", href: "/lab/a/1?t_ns=1", at: 1 });
    record({ key: "season:e:p", world: "season", title: "P", subtitle: "", href: "/season?edition=e", at: 2 });
    record({ key: "match:a/1", world: "match", title: "A", subtitle: "", href: "/lab/a/1?t_ns=2", at: 3 });
    const entries = useRecentContexts.getState().entries;
    expect(entries.map((entry) => entry.key)).toEqual(["match:a/1", "season:e:p"]);
    expect(lastContextOf(entries, "match")?.href).toBe("/lab/a/1?t_ns=2");
    expect(lastContextOf(entries, "game")).toBeNull();
    clear();
  });

  it("describes elapsed time in words", () => {
    expect(relativeTime(0, 30_000)).toBe("just now");
    expect(relativeTime(0, 5 * 60_000)).toBe("5 min ago");
    expect(relativeTime(0, 3 * 3_600_000)).toBe("3 h ago");
    expect(relativeTime(0, 26 * 3_600_000)).toBe("yesterday");
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
