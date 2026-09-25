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
    hoveredEntityId: null,
    selectedTeamId: null,
    selectedTacticalObjectId: null,
    hoveredTacticalObjectId: null,
    tacticalRelationMode: "off",
    scalarFieldMode: "heatmap",
    hoveredJoint: null,
    focusedPanel: "overview",
    interacting: false,
    subjectSwitching: false,
    switchingFromSubjectId: null,
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
    store.setPlaybackDirection(-1);
    expect(useAnalysisStore.getState().playbackDirection).toBe(-1);
  });

  it("hydrates durable context from a deep link and resets transients", () => {
    const store = useAnalysisStore.getState();
    store.hydrate({
      committedTimeNs: 42n,
      committedRangeNs: { fromNs: 1n, toNs: 2n },
      focusedPanel: "pose",
    });
    expect(useAnalysisStore.getState().playheadNs).toBe(42n);
    expect(useAnalysisStore.getState().focusedPanel).toBe("pose");
    store.setHoverTime(9n);
    store.setPlaying(true);
    store.setNominalRate(25);
    store.hoverEntity("entity-1");
    store.selectTeam("home");
    store.selectTacticalObject("zone-1");
    store.hoverTacticalObject("zone-2");
    store.setTacticalRelationMode("selected-triangles");
    store.setScalarFieldMode("elevation");
    store.hoverJoint("knee");
    store.selectJoint("knee");
    useAnalysisStore.getState().resetTransient();
    const state = useAnalysisStore.getState();
    expect(state.hoverTimeNs).toBeNull();
    expect(state.playing).toBe(false);
    expect(state.playheadNs).toBeNull();
    expect(state.nominalRateHz).toBeNull();
    expect(state.hoveredEntityId).toBeNull();
    expect(state.selectedTeamId).toBeNull();
    expect(state.selectedTacticalObjectId).toBeNull();
    expect(state.hoveredTacticalObjectId).toBeNull();
    expect(state.tacticalRelationMode).toBe("off");
    expect(state.scalarFieldMode).toBe("heatmap");
    expect(state.hoveredJoint).toBeNull();
    expect(state.selectedJoint).toBeNull();
    expect(state.committedTimeNs).toBe(42n);
  });

  it("stops and clears a subject switch before applying its resolved target time", () => {
    const store = useAnalysisStore.getState();
    store.commitTime(17n);
    store.setPlayhead(18n);
    store.setPlaying(true);
    store.setBrushRange({ fromNs: 1n, toNs: 2n });
    store.hoverEntity("SC-P1");
    store.selectJoint("nose");
    store.beginSubjectSwitch("SC-P1");

    let state = useAnalysisStore.getState();
    expect(state.playing).toBe(false);
    expect(state.playheadNs).toBe(18n);
    expect(state.committedTimeNs).toBe(17n);
    expect(state.brushRangeNs).toBeNull();
    expect(state.hoveredEntityId).toBeNull();
    expect(state.selectedJoint).toBeNull();
    expect(state.subjectSwitching).toBe(true);
    expect(state.switchingFromSubjectId).toBe("SC-P1");

    state.beginSubjectSwitch("SC-P1", 32n);
    state = useAnalysisStore.getState();
    expect(state.playheadNs).toBe(32n);
    expect(state.committedTimeNs).toBe(32n);
    state.finishSubjectSwitch();
    expect(useAnalysisStore.getState().switchingFromSubjectId).toBeNull();
  });
});
