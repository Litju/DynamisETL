import { Autocomplete } from "@base-ui/react/autocomplete";
import { useRouterState } from "@tanstack/react-router";
import { ArrowRight, CornerDownLeft, Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { useGoTo } from "@/components/common/AppLink";
import { ReadinessGlyph } from "@/components/common/Readiness";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { searchCatalog } from "@/lib/catalog-model";
import { useAnalysisStore } from "@/lib/state/analysis";
import { lastContextOf, relativeTime, useRecentContexts } from "@/lib/state/recent";
import { useUiStore } from "@/lib/state/ui";
import { formatNsDecimal } from "@/lib/time";
import { useCatalog } from "@/lib/use-catalog";
import { WORLD_IDS, WORLDS, type LinkTarget, type WorldId } from "@/lib/worlds";

interface PaletteItem {
  readonly id: string;
  readonly label: string;
  readonly detail?: string | undefined;
  readonly world?: WorldId | null | undefined;
  readonly ready?: boolean | undefined;
  readonly hint?: string | undefined;
  readonly run: () => void;
}

interface PaletteGroup {
  readonly value: string;
  readonly items: readonly PaletteItem[];
}

function matches(item: PaletteItem, needle: string): boolean {
  if (!needle) return true;
  return `${item.label} ${item.detail ?? ""}`.toLowerCase().includes(needle);
}

export function PaletteBody({ onDone }: { onDone: () => void }) {
  const [query, setQuery] = useState("");
  const goTo = useGoTo();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const catalog = useCatalog();
  const recents = useRecentContexts((state) => state.entries);
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  const toggleFocusMode = useUiStore((state) => state.toggleFocusMode);
  const inLab = pathname.startsWith("/lab/") && pathname.split("/").filter(Boolean).length >= 3;

  const groups = useMemo<PaletteGroup[]>(() => {
    const needle = query.trim().toLowerCase();
    const go = (target: LinkTarget | string, transition = true) => () => goTo(target, { transition });
    const result: PaletteGroup[] = [];

    if (!needle && recents.length) {
      result.push({
        value: "Continue",
        items: recents.slice(0, 4).map((entry) => ({
          id: `recent:${entry.key}`,
          label: entry.title,
          detail: entry.subtitle,
          world: entry.world,
          hint: relativeTime(entry.at),
          run: go(entry.href),
        })),
      });
    }

    const worlds: PaletteItem[] = WORLD_IDS.map((id) => {
      const last = lastContextOf(recents, id);
      return {
        id: `world:${id}`,
        label: `${WORLDS[id].label}`,
        detail: last ? `Resume ${last.title}` : WORLDS[id].question,
        world: id,
        hint: last ? "Resume" : "Enter",
        run: go(last?.href ?? WORLDS[id].entry),
      };
    }).filter((item) => matches(item, needle));
    if (worlds.length) result.push({ value: "Worlds", items: worlds });

    if (needle) {
      const hits = searchCatalog(catalog.resources, catalog.studies, needle, 10);
      if (hits.length) {
        result.push({
          value: "Data",
          items: hits.map((hit) => ({
            id: hit.key,
            label: hit.title,
            detail: hit.subtitle,
            world: hit.world,
            ready: hit.ready,
            hint: hit.kind,
            run: go(hit.target),
          })),
        });
      }
    }

    const sections: PaletteItem[] = [
      { id: "go-research", label: "Research", detail: "Continue and start analysis", run: go("/") },
      { id: "go-sports", label: "Data · Sports", detail: "Football, basketball, ice hockey", run: go("/data?domain=sports") },
      { id: "go-human", label: "Data · Human Performance", detail: "Force, IMU, GNSS, LPT", run: go("/data?domain=human") },
      { id: "go-library", label: "Library", detail: "Metrics, methods, protocols, rights", run: go("/library") },
      { id: "go-methods", label: "Library · Methodology", detail: "Metric definitions and lineage", run: go("/methods") },
      { id: "go-runs", label: "Library · Processing runs", detail: "Reproducible run evidence", run: go("/runs") },
      { id: "go-quality", label: "Library · Quality & rights", detail: "Validity and usage boundaries", run: go("/quality") },
      { id: "go-compare", label: "Compare sessions", detail: "Performance World comparison", run: go("/compare") },
    ].filter((item) => matches(item, needle));
    if (sections.length) result.push({ value: "Go to", items: sections });

    const view: PaletteItem[] = [
      {
        id: "toggle-theme",
        label: theme === "dark" ? "Switch to Report Light" : "Switch to Instrument Dark",
        detail: "Theme",
        run: () => setTheme(theme === "dark" ? "light" : "dark"),
      },
      { id: "focus-panel", label: "Toggle focus mode", detail: "Hide chrome around the workbench", hint: "F", run: toggleFocusMode },
    ];
    if (inLab) {
      view.push(
        {
          id: "play-pause",
          label: "Play / pause playback",
          detail: "Transport",
          hint: "Space",
          run: () => useAnalysisStore.getState().setPlaying(!useAnalysisStore.getState().playing),
        },
        {
          id: "reset-transient",
          label: "Clear ephemeral selection",
          detail: "Transport",
          run: () => {
            useAnalysisStore.getState().setBrushRange(null);
            useAnalysisStore.getState().resetTransient();
          },
        },
        {
          id: "copy-time",
          label: "Copy committed time (ns)",
          detail: "Transport",
          run: () => {
            const time = useAnalysisStore.getState().committedTimeNs;
            if (time !== null) void navigator.clipboard?.writeText(formatNsDecimal(time));
          },
        },
      );
    }
    const viewMatches = view.filter((item) => matches(item, needle));
    if (viewMatches.length) result.push({ value: "Actions", items: viewMatches });
    return result;
  }, [catalog.resources, catalog.studies, goTo, inLab, query, recents, setTheme, theme, toggleFocusMode]);

  return (
    <Autocomplete.Root
      open
      inline
      items={groups as PaletteGroup[]}
      filter={null}
      value={query}
      onValueChange={(value) => setQuery(value)}
      itemToStringValue={(item: PaletteItem) => item.label}
      autoHighlight="always"
      keepHighlight
    >
      <Autocomplete.InputGroup className="flex h-12 shrink-0 items-center gap-2.5 border-b border-border-subtle px-4">
        <Search size={15} aria-hidden="true" className="text-text-muted" />
        <Autocomplete.Input
          // The body may mount after the dialog opened (lazy chunk); take
          // focus on mount so typing starts immediately.
          autoFocus
          aria-label="Command search"
          placeholder="Search matches, teams, competitions, studies — or jump to a World"
          className="h-full w-full bg-transparent text-[13.5px] text-text-primary outline-none placeholder:text-text-faint"
        />
        <kbd className="d-kbd">Esc</kbd>
      </Autocomplete.InputGroup>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1.5">
        <Autocomplete.Empty>
          <p className="px-3 py-6 text-center text-[12px] text-text-muted">
            Nothing matches “{query}”. Search covers catalog metadata only.
          </p>
        </Autocomplete.Empty>
        <Autocomplete.List>
          {(group: PaletteGroup) => (
            <Autocomplete.Group key={group.value} items={group.items as PaletteItem[]} className="mb-1.5 last:mb-0">
              <Autocomplete.GroupLabel className="t-kicker px-2.5 pb-1 pt-2">{group.value}</Autocomplete.GroupLabel>
              <Autocomplete.Collection>
                {(item: PaletteItem) => (
                  <Autocomplete.Item
                    key={item.id}
                    value={item}
                    onClick={() => {
                      item.run();
                      onDone();
                    }}
                    className="group grid min-h-9 cursor-default grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-2 rounded-[6px] px-2.5 py-1.5 outline-none data-[highlighted]:bg-hover"
                  >
                    <span className="flex justify-center text-text-muted group-data-[highlighted]:text-accent">
                      {item.world ? <WorldGlyph world={item.world} size="sm" /> : <ArrowRight size={13} aria-hidden="true" />}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate text-[12.5px] text-text-primary">{item.label}</span>
                      {item.detail ? <span className="block truncate text-[11px] text-text-muted">{item.detail}</span> : null}
                    </span>
                    <span className="flex items-center gap-2 text-[10.5px] text-text-muted">
                      {item.ready === false ? (
                        <span className="inline-flex items-center gap-1"><ReadinessGlyph kind="upstream" />Upstream</span>
                      ) : item.ready ? (
                        <span className="inline-flex items-center gap-1"><ReadinessGlyph kind="ready" />Ready</span>
                      ) : null}
                      {item.hint ? <span className="capitalize">{item.hint}</span> : null}
                      <CornerDownLeft size={12} aria-hidden="true" className="opacity-0 group-data-[highlighted]:opacity-100" />
                    </span>
                  </Autocomplete.Item>
                )}
              </Autocomplete.Collection>
            </Autocomplete.Group>
          )}
        </Autocomplete.List>
      </div>
      <PaletteFooter>
        <span className="flex items-center gap-1.5"><kbd className="d-kbd">↑</kbd><kbd className="d-kbd">↓</kbd> navigate</span>
        <span className="flex items-center gap-1.5"><kbd className="d-kbd">Enter</kbd> open</span>
        <span className="ml-auto">Metadata only · no dense data is fetched from search</span>
      </PaletteFooter>
    </Autocomplete.Root>
  );
}

function PaletteFooter({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-9 shrink-0 items-center gap-4 border-t border-border-subtle px-4 text-[10.5px] text-text-muted">
      {children}
    </div>
  );
}
