import { beforeEach, describe, expect, it } from "vitest";

import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";

function reset() {
  useAnalysisStore.setState({
    playheadNs: null,
    committedTimeNs: null,
    hoverTimeNs: null,
    brushRangeNs: null,
    committedRangeNs: null,
    playing: false,
    playbackRate: 1,
    nominalRateHz: null,
    selectedEntityId: null,
    hoveredEntityId: null,
    hoveredJoint: null,
    focusedPanel: "overview",
    interacting: false,
  });
}

describe("transient analysis state spine", () => {
  beforeEach(reset);

  it("separates live playback time from committed time", () => {
    const store = useAnalysisStore.getState();
    store.setPlaying(true);
    store.setPlayhead(1_000_000_000n);
    store.setPlayhead(1_500_000_000n);
    expect(useAnalysisStore.getState().committedTimeNs).toBeNull();
    expect(effectiveTimeNs(useAnalysisStore.getState())).toBe(1_500_000_000n);
    store.commitTime(1_500_000_000n);
    expect(useAnalysisStore.getState().committedTimeNs).toBe(1_500_000_000n);
  });

  it("keeps hover ephemeral and separates transient from committed brush", () => {
    const store = useAnalysisStore.getState();
    store.setHoverTime(5n);
    expect(useAnalysisStore.getState().hoverTimeNs).toBe(5n);
    expect(useAnalysisStore.getState().committedTimeNs).toBeNull();
    store.setBrushRange({ fromNs: 0n, toNs: 10n });
    expect(useAnalysisStore.getState().committedRangeNs).toBeNull();
    store.commitRange({ fromNs: 0n, toNs: 10n });
    expect(useAnalysisStore.getState().committedRangeNs).toEqual({ fromNs: 0n, toNs: 10n });
  });

  it("normalizes playback rate and nominal rate", () => {
    const store = useAnalysisStore.getState();
    store.setPlaybackRate(-3);
    expect(useAnalysisStore.getState().playbackRate).toBe(1);
    store.setNominalRate(0);
    expect(useAnalysisStore.getState().nominalRateHz).toBeNull();
    store.setNominalRate(25);
    expect(useAnalysisStore.getState().nominalRateHz).toBe(25);
  });

  it("hydrates durable context from a deep link and resets transients", () => {
    const store = useAnalysisStore.getState();
    store.hydrate({
      committedTimeNs: 42n,
      committedRangeNs: { fromNs: 1n, toNs: 2n },
      selectedEntityId: "SC-P1",
      focusedPanel: "pose",
    });
    expect(useAnalysisStore.getState().playheadNs).toBe(42n);
    expect(useAnalysisStore.getState().focusedPanel).toBe("pose");
    store.setHoverTime(9n);
    store.setPlaying(true);
    useAnalysisStore.getState().resetTransient();
    const state = useAnalysisStore.getState();
    expect(state.hoverTimeNs).toBeNull();
    expect(state.playing).toBe(false);
    expect(state.playheadNs).toBeNull();
    // Committed identity survives transient resets.
    expect(state.committedTimeNs).toBe(42n);
    expect(state.selectedEntityId).toBe("SC-P1");
  });
});
