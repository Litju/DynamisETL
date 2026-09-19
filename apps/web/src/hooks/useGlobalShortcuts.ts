import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";

import { useAnalysisStore, effectiveTimeNs } from "@/lib/state/analysis";
import { useUiStore } from "@/lib/state/ui";
import { formatNsDecimal, stepFrames } from "@/lib/time";

function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  if (!element) return false;
  return (
    element.tagName === "INPUT" ||
    element.tagName === "TEXTAREA" ||
    element.tagName === "SELECT" ||
    element.isContentEditable
  );
}

/**
 * Global keyboard workflow. Shortcuts never override text-input behavior and
 * only transport commands inside a laboratory route may commit durable time.
 */
export function useGlobalShortcuts(): void {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const setPaletteOpen = useUiStore((state) => state.setPaletteOpen);
  const paletteOpen = useUiStore((state) => state.paletteOpen);
  const toggleFocusMode = useUiStore((state) => state.toggleFocusMode);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const parts = pathname.split("/").filter(Boolean);
      const isLab = parts[0] === "lab" && Boolean(parts[1]) && Boolean(parts[2]);
      const datasetId = parts[1] ?? "";
      const sessionId = parts[2] ?? "";
      const analysis = useAnalysisStore.getState();

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(!paletteOpen);
        return;
      }
      if (event.key === "Escape") {
        analysis.setHoverTime(null);
        analysis.setBrushRange(null);
        return;
      }
      if (isTypingTarget(event.target)) return;

      if (event.key === "f" || event.key === "F") {
        toggleFocusMode();
        return;
      }
      if (!isLab) return;

      const commit = (tNs: bigint) => {
        analysis.setPlayhead(tNs);
        void navigate({
          to: "/lab/$datasetId/$sessionId",
          params: { datasetId, sessionId },
          search: (previous: Record<string, unknown>) => ({
            ...previous,
            t_ns: formatNsDecimal(tNs),
          }),
          replace: true,
        });
      };

      if (event.key === " ") {
        event.preventDefault();
        const next = !analysis.playing;
        analysis.setPlaying(next);
        if (!next) {
          const now = effectiveTimeNs(useAnalysisStore.getState());
          if (now !== null) commit(now);
        }
        return;
      }
      const stepRate = analysis.nominalRateHz ?? 25;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        const current = effectiveTimeNs(useAnalysisStore.getState());
        if (current === null) return;
        event.preventDefault();
        const frames = (event.shiftKey ? 10 : 1) * (event.key === "ArrowRight" ? 1 : -1);
        commit(stepFrames(current, frames, stepRate));
        return;
      }
      if (event.key === "r" || event.key === "R") {
        analysis.setBrushRange(null);
        analysis.commitRange(null);
        analysis.setHoverTime(null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate, paletteOpen, pathname, setPaletteOpen, toggleFocusMode]);
}
