import { useRouterState } from "@tanstack/react-router";
import { PanelLeftClose, PanelLeftOpen, PanelRight } from "lucide-react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { lazy, Suspense, useState, type ReactNode } from "react";

import { CommandPalette } from "@/components/command/CommandPalette";
import { ContextBar } from "@/components/shell/ContextBar";
import { Explorer } from "@/components/shell/Explorer";
import { Inspector } from "@/components/shell/Inspector";
import { NavRail } from "@/components/shell/NavRail";
import { Transport } from "@/components/shell/Transport";
import { useGlobalShortcuts } from "@/hooks/useGlobalShortcuts";
import { usePlaybackClock } from "@/hooks/usePlaybackClock";
import { useAnalysisStore } from "@/lib/state/analysis";
import { inspectorVisible, useUiStore } from "@/lib/state/ui";
import { normalizeLabSearch } from "@/lib/search";

const TacticalAnalysisPane = lazy(() => import("@/components/shell/TacticalAnalysisPane").then((module) => ({ default: module.TacticalAnalysisPane })));
const PoseAnalysisPane = lazy(() => import("@/components/pose/PoseAnalysisPane").then((module) => ({ default: module.PoseAnalysisPane })));

export interface ShellLayout {
  /** The session explorer only exists inside an open laboratory session. */
  readonly explorer: boolean;
  /** Route default for the evidence pane, before any user override. */
  readonly inspector: boolean;
  /** The transport is a laboratory instrument, not global chrome. */
  readonly transport: boolean;
}

/**
 * Decide which shell regions a route earns.
 *
 * A pane that has nothing to show must not reserve flagship width, so the
 * explorer, inspector and transport are granted per route rather than rendered
 * everywhere: only an open laboratory session has a stream hierarchy to browse,
 * a selection to inspect and a timebase to play.
 */
export function shellLayoutFor(pathname: string): ShellLayout {
  const parts = pathname.split("/").filter(Boolean);
  const inLabSession = parts[0] === "lab" && Boolean(parts[1]) && Boolean(parts[2]);
  return {
    explorer: inLabSession,
    inspector: inLabSession,
    transport: inLabSession,
  };
}

/**
 * Fixed-viewport workbench shell: context spine, activity rail, contextual
 * explorer, flexible workbench, evidence inspector and a laboratory transport.
 * Panels scroll internally; the document itself never becomes one giant
 * dashboard scroll.
 */
export function AppShell({ children }: { children: ReactNode }) {
  usePlaybackClock();
  useGlobalShortcuts();
  const location = useRouterState({ select: (state) => state.location });
  const pathname = location.pathname;
  const focusMode = useUiStore((state) => state.focusMode);
  const inspectorOverride = useUiStore((state) => state.inspectorOpen);
  const setInspectorOpen = useUiStore((state) => state.setInspectorOpen);
  const nominalRateHz = useAnalysisStore((state) => state.nominalRateHz);

  const layout = shellLayoutFor(pathname);
  const routeSearch = normalizeLabSearch(location.search);
  const routeView = routeSearch.view;
  const matchLabRoute = routeView === "matchlab";
  const showExplorer = !focusMode && layout.explorer && !matchLabRoute;
  const poseRoute = routeView === "pose";
  const showPoseTelemetry = !focusMode && layout.inspector && poseRoute;
  const tacticalRoute = !focusMode && layout.inspector && routeView === "field";
  const showTacticalAnalysis = tacticalRoute && inspectorVisible(inspectorOverride, layout.inspector);
  const showInspector =
    !matchLabRoute && (showPoseTelemetry || showTacticalAnalysis || (!focusMode && inspectorVisible(inspectorOverride, layout.inspector)));

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-0 text-text-primary">
      <ContextBar />
      <div className="flex min-h-0 flex-1">
        {!focusMode ? <NavRail /> : null}
        {matchLabRoute && !focusMode ? <MatchLabExplorerRail /> : null}
        <Group
          orientation="horizontal"
          id="dynamis-workbench"
          className="min-h-0 flex-1"
          resizeTargetMinimumSize={{ coarse: 28, fine: 6 }}
        >
          {showExplorer ? (
            <>
              <Panel
                id="explorer"
                defaultSize="17%"
                minSize="12%"
                maxSize="28%"
                className="min-w-0 border-r border-border-subtle bg-surface-1"
              >
                <Explorer />
              </Panel>
              <Separator className="w-px bg-border-subtle transition-colors duration-quick data-[separator]:hover:bg-accent" />
            </>
          ) : null}
          <Panel id="workbench" className="min-w-0 bg-surface-0">
            <main className="h-full min-h-0 overflow-hidden">{children}</main>
          </Panel>
          {showInspector ? (
            <>
              <Separator className="w-px bg-border-subtle transition-colors duration-quick data-[separator]:hover:bg-accent" />
              <Panel
                id="inspector"
                defaultSize="25%"
                minSize="18%"
                maxSize="40%"
                className="min-w-0"
              >
                {showPoseTelemetry ? (
                  <Suspense fallback={<div className="p-3 text-[11px] text-text-muted">Loading Pose analysis pane…</div>}>
                    <PoseAnalysisPane />
                  </Suspense>
                ) : showTacticalAnalysis ? (
                  <Suspense fallback={null}>
                    <TacticalAnalysisPane onCollapse={() => setInspectorOpen(false)} />
                  </Suspense>
                ) : (
                  <Inspector onCollapse={() => setInspectorOpen(false)} />
                )}
              </Panel>
            </>
          ) : null}
        </Group>
        {!focusMode && !matchLabRoute && !showInspector ? (
        <InspectorRail tactical={tacticalRoute} onExpand={() => setInspectorOpen(true)} />
        ) : null}
      </div>
      {layout.transport ? <Transport nominalRateHz={nominalRateHz} /> : null}
      <CommandPalette />
    </div>
  );
}

/** Narrow, on-demand source/context rail for the flagship MatchLab route. */
function MatchLabExplorerRail() {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="relative z-30 h-full w-8 shrink-0 border-r border-border-subtle bg-surface-0">
      <button
        type="button"
        onClick={() => setExpanded((open) => !open)}
        aria-label={expanded ? "Close MatchLab explorer" : "Open MatchLab explorer"}
        aria-expanded={expanded}
        className="flex h-8 w-8 items-center justify-center border-b border-border-subtle text-text-muted hover:bg-surface-2 hover:text-text-secondary"
      >
        {expanded ? <PanelLeftClose size={14} aria-hidden="true" /> : <PanelLeftOpen size={14} aria-hidden="true" />}
      </button>
      <span aria-hidden="true" className="t-section mt-3 block select-none text-center text-[9px] text-text-muted" style={{ writingMode: "vertical-rl" }}>
        Explorer
      </span>
      {expanded ? (
        <aside className="absolute inset-y-0 left-full z-30 w-64 border-r border-border-subtle bg-surface-1 shadow-panel">
          <Explorer onCollapse={() => setExpanded(false)} />
        </aside>
      ) : null}
    </div>
  );
}

/**
 * Collapsed evidence pane: a rail, not a blank column. It keeps the inspector
 * one click away on surfaces that already own their own evidence, without
 * spending viewport on a pane that would only say "no data".
 */
function InspectorRail({ onExpand, tactical = false }: { onExpand: () => void; tactical?: boolean }) {
  return (
    <div className="flex w-8 shrink-0 flex-col items-center border-l border-border-subtle bg-surface-0 py-2">
      <button
        type="button"
        onClick={onExpand}
        aria-label={`Open the ${tactical ? "tactical analysis" : "inspector"}`}
        title={tactical ? "Open tactical analysis" : "Open the inspector (method, provenance, quality, rights)"}
        className="flex size-7 items-center justify-center rounded-control text-text-muted transition-colors duration-quick hover:bg-surface-2 hover:text-text-secondary"
      >
        <PanelRight size={15} aria-hidden="true" />
      </button>
      <span
        aria-hidden="true"
        className="t-section mt-3 select-none text-text-muted tracking-[0.18em]"
        style={{ writingMode: "vertical-rl" }}
      >
        {tactical ? "Tactical" : "Inspector"}
      </span>
    </div>
  );
}
