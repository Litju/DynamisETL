import { useState, useSyncExternalStore } from "react";

import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";

/** A throttled view of the analysis-store playhead, as an external store. */
class ThrottledPlayhead {
  private value: bigint | null = effectiveTimeNs(useAnalysisStore.getState());
  private last = 0;
  private pending: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly intervalMs: number) {}

  read = (): bigint | null => this.value;

  subscribe = (notify: () => void): (() => void) => {
    const publish = () => {
      const next = effectiveTimeNs(useAnalysisStore.getState());
      if (next === this.value) return;
      this.value = next;
      this.last = performance.now();
      notify();
    };
    const unsubscribe = useAnalysisStore.subscribe((state, previous) => {
      if (effectiveTimeNs(state) === effectiveTimeNs(previous)) return;
      const now = performance.now();
      if (!state.playing || now - this.last >= this.intervalMs) {
        if (this.pending !== null) clearTimeout(this.pending);
        this.pending = null;
        publish();
        return;
      }
      if (this.pending === null) {
        this.pending = setTimeout(() => {
          this.pending = null;
          publish();
        }, this.intervalMs - (now - this.last));
      }
    });
    // A commit between the first render and this subscription (route
    // hydration) is published immediately.
    publish();
    return () => {
      unsubscribe();
      if (this.pending !== null) clearTimeout(this.pending);
      this.pending = null;
    };
  };
}

/**
 * The effective playhead for text read-outs, at most every `intervalMs` while
 * playing and immediately otherwise. Panels that summarise the current frame
 * must not re-render on every animation frame.
 */
export function useThrottledPlayhead(intervalMs = 200): bigint | null {
  const [store] = useState(() => new ThrottledPlayhead(intervalMs));
  return useSyncExternalStore(store.subscribe, store.read, store.read);
}
