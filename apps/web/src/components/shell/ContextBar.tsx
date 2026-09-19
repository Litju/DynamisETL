import { useQuery } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { Command, Moon, Sun } from "lucide-react";

import { servingStatusQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/lib/state/ui";

interface ContextSegment {
  readonly label: string;
  readonly value: string;
  readonly mono?: boolean;
}

/** Parse the durable context out of the current location for the context bar. */
export function contextSegments(pathname: string, search: string): ContextSegment[] {
  const segments: ContextSegment[] = [];
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] === "lab" && parts[1]) {
    segments.push({ label: "dataset", value: parts[1], mono: true });
    if (parts[2]) segments.push({ label: "session", value: parts[2], mono: true });
  } else if (parts[0]) {
    segments.push({ label: "surface", value: parts[0] });
  }
  const params = new URLSearchParams(search);
  for (const key of ["trial", "subject", "metric"] as const) {
    const value = params.get(key);
    if (value) segments.push({ label: key, value, mono: key !== "subject" });
  }
  return segments;
}

export function ContextBar() {
  const location = useRouterState({ select: (state) => state.location });
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  const setPaletteOpen = useUiStore((state) => state.setPaletteOpen);
  const { data: status, isError } = useQuery(servingStatusQuery());
  const segments = contextSegments(location.pathname, location.searchStr ?? "");

  const databaseOk = Boolean(status) && !isError;
  const goldPublished = status?.gold_published === true;

  return (
    <header className="flex h-10 shrink-0 items-center gap-3 border-b border-border-subtle bg-surface-0 px-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="whitespace-nowrap text-[13px] font-semibold tracking-tight">
          DynamisData <span className="text-text-muted">Performance Laboratory</span>
        </span>
        <div className="flex min-w-0 items-center gap-2 overflow-hidden">
          {segments.map((segment) => (
            <span
              key={segment.label}
              className="flex min-w-0 items-center gap-1 text-[12px] text-text-secondary"
            >
              <span className="text-[10px] uppercase tracking-wider text-text-muted">
                {segment.label}
              </span>
              <span className={cn("truncate", segment.mono && "mono")}>{segment.value}</span>
            </span>
          ))}
        </div>
      </div>

      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        className="ml-auto flex h-6 w-64 items-center gap-2 rounded-control border border-border-subtle bg-surface-1 px-2 text-left text-[12px] text-text-muted hover:border-border-strong"
      >
        <Command size={12} aria-hidden="true" />
        <span className="flex-1 truncate">Search or run a command</span>
        <kbd className="mono rounded-[3px] border border-border-subtle px-1 text-[10px]">⌘K</kbd>
      </button>

      <div
        className="flex items-center gap-1.5 text-[11px] text-text-muted"
        title={
          databaseOk
            ? `serving database ready (${status?.db_schema}); gold schema ${goldPublished ? "published" : "not published"}`
            : "serving database unavailable"
        }
      >
        <span
          aria-hidden="true"
          className="size-1.5 rounded-full"
          style={{
            backgroundColor: databaseOk
              ? "var(--d-quality-valid)"
              : "var(--d-quality-unavailable)",
          }}
        />
        <span>{databaseOk ? (goldPublished ? "gold" : "control") : "offline"}</span>
      </div>

      <button
        type="button"
        aria-label={theme === "dark" ? "Switch to Report Light" : "Switch to Instrument Dark"}
        title={theme === "dark" ? "Switch to Report Light" : "Switch to Instrument Dark"}
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        className="flex size-6 items-center justify-center rounded-control text-text-muted hover:bg-surface-2 hover:text-text-secondary"
      >
        {theme === "dark" ? (
          <Sun size={13} aria-hidden="true" />
        ) : (
          <Moon size={13} aria-hidden="true" />
        )}
      </button>
    </header>
  );
}
