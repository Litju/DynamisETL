import { Menu } from "@base-ui/react/menu";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, Moon, Search, Sun } from "lucide-react";
import { LayoutGroup, motion } from "motion/react";

import { AppLink, useGoTo } from "@/components/common/AppLink";
import { BrowserReadiness, ReadinessGlyph, SERVER_TEXT, ServerReadiness, serverGlyph } from "@/components/common/Readiness";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { datasetsQuery, servingStatusQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { useShellContext, type Crumb } from "@/lib/state/context";
import { lastContextOf, relativeTime, useRecentContexts } from "@/lib/state/recent";
import { useUiStore } from "@/lib/state/ui";
import { WORLD_IDS, WORLDS, worldForLocation, type Section, type WorldId } from "@/lib/worlds";

const SECTIONS: readonly { id: Exclude<Section, "world" | "other">; label: string; to: string }[] = [
  { id: "research", label: "Research", to: "/" },
  { id: "data", label: "Data", to: "/data" },
  { id: "library", label: "Library", to: "/library" },
];

/**
 * Global top bar: product sections, the active World, and the readable
 * context spine. One 44 px row; analytical space below stays dominant.
 */
export function TopBar() {
  const location = useRouterState({ select: (state) => state.location });
  const datasets = useQuery(datasetsQuery());
  const datasetId = location.pathname.startsWith("/lab/") ? location.pathname.split("/")[2] : undefined;
  const domain = datasetId ? datasets.data?.find((dataset) => dataset.dataset_id === datasetId)?.domain ?? null : null;
  const where = worldForLocation(location.pathname, location.search as Record<string, unknown>, domain);
  const context = useShellContext((state) => state.context);
  const world = where.world;

  return (
    <header className="relative z-40 flex h-11 shrink-0 items-center gap-2 border-b border-border-subtle bg-surface-0 pl-3 pr-2">
      <Brand />
      <SectionNav section={where.section} />
      <span aria-hidden="true" className="mx-1 h-4 w-px bg-border-subtle" />
      <WorldSwitcher active={world} />
      <ContextSpine crumbs={world || where.section !== "research" ? context?.crumbs ?? [] : []} />
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        {world && context?.readiness ? <SpineReadiness readiness={context.readiness} /> : null}
        <CommandTrigger />
        <ServingStatus />
        <ThemeToggle />
      </div>
    </header>
  );
}

function Brand() {
  return (
    <Link
      to="/"
      className="group flex shrink-0 items-center gap-2 rounded-control pr-1"
      title="DynamisData — Research"
      aria-label="DynamisData home"
    >
      <svg viewBox="0 0 20 20" aria-hidden="true" className="size-[18px] text-accent">
        <rect x="1" y="1" width="18" height="18" rx="5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path d="M6 5.5 V14.5 H9.5 A4.5 4.5 0 0 0 9.5 5.5 Z" fill="currentColor" opacity="0.9" />
      </svg>
      <span className="text-[13px] font-semibold tracking-[-0.02em] text-text-primary">Dynamis</span>
    </Link>
  );
}

function SectionNav({ section }: { section: Section }) {
  return (
    <LayoutGroup id="section-nav">
      <nav aria-label="Product sections" className="flex items-center">
        {SECTIONS.map((item) => {
          const active = section === item.id;
          return (
            <Link
              key={item.id}
              to={item.to}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex h-11 items-center px-2.5 text-[12px] font-medium transition-colors duration-quick",
                active ? "text-text-primary" : "text-text-muted hover:text-text-secondary",
              )}
            >
              {item.label}
              {active ? (
                <motion.span
                  layoutId="section-underline"
                  transition={{ duration: 0.22, ease: [0.3, 0, 0, 1] }}
                  aria-hidden="true"
                  className="absolute inset-x-2.5 bottom-0 h-[2px] rounded-full bg-accent"
                />
              ) : null}
            </Link>
          );
        })}
      </nav>
    </LayoutGroup>
  );
}

/** World chip + switcher. Each World resumes its own last context. */
function WorldSwitcher({ active }: { active: WorldId | null }) {
  const recents = useRecentContexts((state) => state.entries);
  const goTo = useGoTo();
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={active ? `${WORLDS[active].label} — switch World` : "Worlds — choose a World"}
        className={cn(
          "group flex h-7 shrink-0 items-center gap-1.5 rounded-control border px-2 text-[12px] transition-colors duration-quick",
          active
            ? "border-selected-border bg-selected text-text-primary"
            : "border-border-subtle text-text-muted hover:border-border-strong hover:text-text-secondary",
        )}
        style={{ viewTransitionName: "d-world-chip" }}
      >
        {active ? <WorldGlyph world={active} size="sm" className="text-accent" /> : null}
        <span className="font-medium">{active ? WORLDS[active].label : "Worlds"}</span>
        <ChevronDown size={12} aria-hidden="true" className="text-text-muted" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner sideOffset={6} align="start" className="z-50">
          <Menu.Popup className="d-overlay d-pop w-[26rem] p-1 outline-none">
            <div className="t-kicker px-2.5 pb-1.5 pt-2">Worlds</div>
            {WORLD_IDS.map((id) => {
              const last = lastContextOf(recents, id);
              return (
                <Menu.Item
                  key={id}
                  onClick={() => goTo(last?.href ?? WORLDS[id].entry, { transition: true })}
                  className={cn(
                    "group flex cursor-default items-start gap-3 rounded-[6px] px-2.5 py-2 outline-none data-[highlighted]:bg-hover",
                    id === active && "bg-selected",
                  )}
                >
                  <WorldGlyph world={id} className="mt-0.5 text-text-secondary group-data-[highlighted]:text-accent" />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="text-[12.5px] font-medium text-text-primary">{WORLDS[id].label}</span>
                      <span className="text-[10.5px] text-text-muted">{last ? `Resume · ${relativeTime(last.at)}` : "Enter"}</span>
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-text-muted">
                      {last ? last.title : WORLDS[id].question}
                    </span>
                  </span>
                </Menu.Item>
              );
            })}
            <div className="d-rule mx-1 my-1" />
            <Menu.Item
              onClick={() => goTo("/data", { transition: true })}
              className="flex cursor-default items-center justify-between rounded-[6px] px-2.5 py-2 text-[12px] text-text-secondary outline-none data-[highlighted]:bg-hover"
            >
              Browse all data
              <ChevronRight size={13} aria-hidden="true" className="text-text-muted" />
            </Menu.Item>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

function ContextSpine({ crumbs }: { crumbs: readonly Crumb[] }) {
  return (
    <nav
      aria-label="Analysis context"
      className="flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden pl-1"
      style={{ viewTransitionName: "d-context-spine" }}
    >
      {crumbs.map((crumb, index) => {
        const last = index === crumbs.length - 1;
        return (
          <span
            key={crumb.key}
            className={cn(
              "flex min-w-0 items-center gap-0.5",
              // The volatile tail (contest, period, player) never truncates
              // first; long sport/competition names yield space.
              last ? "shrink-0" : index < crumbs.length - 2 ? "shrink-[3]" : "shrink",
            )}
          >
            {index > 0 ? <ChevronRight size={12} aria-hidden="true" className="shrink-0 text-text-faint" /> : null}
            {crumb.pending ? (
              <span className="d-skeleton inline-block h-3 w-24" aria-label={`Resolving ${crumb.kind ?? "context"}`} />
            ) : crumb.target && !last ? (
              <AppLink
                to={crumb.target}
                transition
                title={crumb.kind ? `${crumb.kind}: ${crumb.label}` : crumb.label}
                className="truncate rounded-[4px] px-1 py-0.5 text-[12px] text-text-muted transition-colors duration-quick hover:bg-hover hover:text-text-primary"
              >
                {crumb.label}
              </AppLink>
            ) : (
              <span
                className={cn("truncate px-1 text-[12px]", last ? "font-medium text-text-primary" : "text-text-muted")}
                title={crumb.kind ? `${crumb.kind}: ${crumb.label}` : crumb.label}
                aria-current={last ? "location" : undefined}
              >
                {crumb.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function SpineReadiness({ readiness }: { readiness: NonNullable<ReturnType<typeof useShellContext.getState>["context"]>["readiness"] }) {
  if (!readiness) return null;
  // Glyph-only in the global bar (the text lives in the World's own strip and
  // in the tooltip); full words only when the bar has room to spare.
  const server = readiness.server ? SERVER_TEXT[readiness.server] : null;
  const browser = readiness.browser === "loaded" ? "Loaded in browser" : readiness.browser === "loading" ? "Loading in browser" : readiness.browser ? "Not yet loaded in browser" : null;
  return (
    <span
      className="mr-1 flex items-center gap-2.5"
      role="img"
      aria-label={`Context readiness: ${[server, browser].filter(Boolean).join(", ")}`}
      title={[server, browser].filter(Boolean).join(" · ")}
    >
      {readiness.server ? (
        <span className="hidden min-[1700px]:inline-flex"><ServerReadiness stage={readiness.server} upstream={readiness.upstream !== "unavailable"} compact /></span>
      ) : null}
      {readiness.server ? <ReadinessGlyph kind={serverGlyph(readiness.server, readiness.upstream !== "unavailable")} className="min-[1700px]:hidden" /> : null}
      {readiness.browser ? (
        <span className="hidden min-[1700px]:inline-flex"><BrowserReadiness state={readiness.browser} /></span>
      ) : null}
      {readiness.browser ? <ReadinessGlyph kind={readiness.browser === "loaded" ? "loaded" : "upstream"} className="min-[1700px]:hidden" /> : null}
    </span>
  );
}

function CommandTrigger() {
  const setPaletteOpen = useUiStore((state) => state.setPaletteOpen);
  return (
    <button
      type="button"
      onClick={() => setPaletteOpen(true)}
      className="flex h-7 w-[8.5rem] items-center gap-2 rounded-control border border-border-subtle bg-surface-1 pl-2 pr-1 text-left text-[12px] text-text-muted transition-colors duration-quick hover:border-border-strong hover:text-text-secondary min-[1600px]:w-56"
    >
      <Search size={13} aria-hidden="true" />
      <span className="flex-1 truncate">Search<span className="hidden min-[1600px]:inline"> or jump to…</span></span>
      <kbd className="d-kbd">Ctrl K</kbd>
    </button>
  );
}

function ServingStatus() {
  const { data: status, isError } = useQuery(servingStatusQuery());
  const ok = Boolean(status) && !isError;
  const gold = status?.gold_published === true;
  return (
    <span
      className="flex items-center gap-1.5 px-1.5 text-[11px] text-text-muted"
      title={ok ? `Serving database ready (${status?.db_schema}); Gold ${gold ? "published" : "not published"}` : "Serving API unavailable"}
    >
      <span
        aria-hidden="true"
        className="size-1.5 rounded-full"
        style={{ background: ok ? "var(--d-success)" : "var(--d-danger)" }}
      />
      <span className="hidden lg:inline">{ok ? (gold ? "Gold" : "Control") : "Offline"}</span>
    </span>
  );
}

function ThemeToggle() {
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  const label = theme === "dark" ? "Switch to Report Light" : "Switch to Instrument Dark";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      className="flex size-7 items-center justify-center rounded-control text-text-muted transition-colors duration-quick hover:bg-hover hover:text-text-secondary"
    >
      {theme === "dark" ? <Sun size={14} aria-hidden="true" /> : <Moon size={14} aria-hidden="true" />}
    </button>
  );
}
