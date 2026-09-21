import { useEffect, useRef } from "react";

import { useAnalysisStore } from "@/lib/state/analysis";

/**
 * Wall-clock-driven playback for the shared playhead.
 *
 * The loop mutates only the Zustand playhead (no React state, no URL writes per
 * frame). The laboratory context commits the final time on pause/navigation.
 */
export function usePlaybackClock(): void {
  const frame = useRef<number | null>(null);
  const last = useRef<number | null>(null);
  const playing = useAnalysisStore((state) => state.playing);

  useEffect(() => {
    if (!playing) return;
    const tick = (now: number) => {
      const current = useAnalysisStore.getState();
      if (!current.playing) return;
      const previous = last.current ?? now;
      last.current = now;
      const elapsedMs = Math.max(0, now - previous);
      const elapsedNs = BigInt(Math.round(elapsedMs * 1e6 * current.playbackRate));
      if (elapsedNs > 0n) {
        const base = current.playheadNs ?? current.committedTimeNs ?? 0n;
        current.setPlayhead(base + elapsedNs);
      }
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
      last.current = null;
    };
  }, [playing]);
}
