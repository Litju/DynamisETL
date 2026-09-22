import { useEffect, useRef } from "react";

import { useAnalysisStore } from "@/lib/state/analysis";
import { constrainPlaybackAdvance } from "@/lib/playback-chunk-coordinator";

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
  const playbackDirection = useAnalysisStore((state) => state.playbackDirection);

  useEffect(() => {
    if (!playing) return;
    const tick = (now: number) => {
      const current = useAnalysisStore.getState();
      if (!current.playing) return;
      const previous = last.current ?? now;
      last.current = now;
      const elapsedMs = Math.max(0, now - previous);
      const elapsedNs = BigInt(
        Math.round(elapsedMs * 1e6 * current.playbackRate * current.playbackDirection),
      );
      if (elapsedNs !== 0n) {
        const base = current.playheadNs ?? current.committedTimeNs ?? 0n;
        const requested = base + elapsedNs;
        const next = constrainPlaybackAdvance(base, requested);
        if (next !== base) current.setPlayhead(next);
      }
      frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
      last.current = null;
    };
  }, [playing, playbackDirection]);
}
