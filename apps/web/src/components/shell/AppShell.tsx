import { useRouterState } from "@tanstack/react-router";
import { Group, Panel, Separator } from "react-resizable-panels";
import type { ReactNode } from "react";

import { CommandPalette } from "@/components/command/CommandPalette";
import { ContextBar } from "@/components/shell/ContextBar";
import { Explorer } from "@/components/shell/Explorer";
import { Inspector } from "@/components/shell/Inspector";
import { NavRail } from "@/components/shell/NavRail";
import { Transport } from "@/components/shell/Transport";
import { useGlobalShortcuts } from "@/hooks/useGlobalShortcuts";
import { usePlaybackClock } from "@/hooks/usePlaybackClock";
import { useAnalysisStore } from "@/lib/state/analysis";
import { useUiStore } from "@/lib/state/ui";

const SURFACES_WITH_EXPLORER = ["/catalog", "/lab", "/compare"];

/**
 * Fixed-viewport workbench shell: context bar, activity rail, optional explorer,
 * flexible workbench, inspector and persistent transport. Panels scroll
 * internally; the document itself never becomes one giant dashboard scroll.
 */
export function AppShell({ children }: { children: ReactNode }) {
  usePlaybackClock();
  useGlobalShortcuts();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const focusMode = useUiStore((state) => state.focusMode);
  const nominalRateHz = useAnalysisStore((state) => state.nominalRateHz);
  const showExplorer =
    !focusMode && SURFACES_WITH_EXPLORER.some((surface) => pathname.startsWith(surface));

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-surface-0 text-text-primary">
      <ContextBar />
      <div className="flex min-h-0 flex-1">
        {!focusMode ? <NavRail /> : null}
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
                defaultSize="18%"
                minSize="12%"
                maxSize="30%"
                className="min-w-0 border-r border-border-subtle bg-surface-1"
              >
                <div className="flex h-full min-h-0 flex-col">
                  <header className="flex h-8 shrink-0 items-center border-b border-border-subtle px-3">
                    <h2 className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
                      Explorer
                    </h2>
                  </header>
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    <Explorer />
                  </div>
                </div>
              </Panel>
              <Separator className="w-px bg-border-subtle transition-colors duration-quick data-[separator]:hover:bg-accent" />
            </>
          ) : null}
          <Panel id="workbench" className="min-w-0 bg-surface-0">
            <main className="h-full min-h-0 overflow-auto">{children}</main>
          </Panel>
          {!focusMode ? (
            <>
              <Separator className="w-px bg-border-subtle transition-colors duration-quick data-[separator]:hover:bg-accent" />
              <Panel
                id="inspector"
                defaultSize="26%"
                minSize="20%"
                maxSize="40%"
                className="min-w-0"
              >
                <Inspector />
              </Panel>
            </>
          ) : null}
        </Group>
      </div>
      <Transport nominalRateHz={nominalRateHz} />
      <CommandPalette />
    </div>
  );
}
