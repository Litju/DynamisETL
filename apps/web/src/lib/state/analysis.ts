/**
 * Transient analysis state spine.
 *
 * Zustand owns only small high-frequency client state: hover, live playback,
 * brush, focused panel, hovered entity/joint and renderer interaction flags.
 * Server data never enters this store, and playback never mutates the URL:
 * `commitTime` is the single boundary that a route may serialize.
 */

import { create } from "zustand";

export type WorkbenchPanel = "overview" | "signals" | "field" | "pose" | "provenance";

export interface TimeRangeNs {
  readonly fromNs: bigint;
  readonly toNs: bigint;
}

export interface AnalysisState {
  /** Live playback/scrub time; high-frequency and never URL-serialized directly. */
  playheadNs: bigint | null;
  /** Latest committed time (pause, click, navigation boundary, replay seek). */
  committedTimeNs: bigint | null;
  /** Ephemeral crosshair time under the pointer. */
  hoverTimeNs: bigint | null;
  /** Transient brush; becomes a committed range only when explicitly applied. */
  brushRangeNs: TimeRangeNs | null;
  committedRangeNs: TimeRangeNs | null;
  playing: boolean;
  playbackRate: number;
  /** Nominal rate of the currently selected stream, for frame stepping. */
  nominalRateHz: number | null;
  selectedEntityId: string | null;
  hoveredEntityId: string | null;
  hoveredJoint: string | null;
  selectedJoint: string | null;
  focusedPanel: WorkbenchPanel;
  /** Renderer interaction flags (camera drag, pitch pan, chart drag). */
  interacting: boolean;

  setPlayhead: (tNs: bigint | null) => void;
  commitTime: (tNs: bigint | null) => void;
  setHoverTime: (tNs: bigint | null) => void;
  setBrushRange: (range: TimeRangeNs | null) => void;
  commitRange: (range: TimeRangeNs | null) => void;
  setPlaying: (playing: boolean) => void;
  setPlaybackRate: (rate: number) => void;
  setNominalRate: (rateHz: number | null) => void;
  selectEntity: (entityId: string | null) => void;
  hoverEntity: (entityId: string | null) => void;
  hoverJoint: (jointId: string | null) => void;
  selectJoint: (jointId: string | null) => void;
  focusPanel: (panel: WorkbenchPanel) => void;
  setInteracting: (interacting: boolean) => void;
  hydrate: (state: {
    committedTimeNs?: bigint | null;
    committedRangeNs?: TimeRangeNs | null;
    selectedEntityId?: string | null;
    focusedPanel?: WorkbenchPanel;
  }) => void;
  resetTransient: () => void;
}

const TRANSIENT_DEFAULTS = {
  playheadNs: null,
  hoverTimeNs: null,
  brushRangeNs: null,
  playing: false,
  nominalRateHz: null,
  hoveredEntityId: null,
  hoveredJoint: null,
  selectedJoint: null,
  interacting: false,
} as const;

export const useAnalysisStore = create<AnalysisState>()((set) => ({
  ...TRANSIENT_DEFAULTS,
  committedTimeNs: null,
  committedRangeNs: null,
  playbackRate: 1,
  nominalRateHz: null,
  selectedEntityId: null,
  hoveredEntityId: null,
  hoveredJoint: null,
  selectedJoint: null,
  focusedPanel: "overview",

  setPlayhead: (tNs) => set({ playheadNs: tNs }),
  commitTime: (tNs) => set({ committedTimeNs: tNs, playheadNs: tNs }),
  setHoverTime: (tNs) => set({ hoverTimeNs: tNs }),
  setBrushRange: (range) => set({ brushRangeNs: range }),
  commitRange: (range) => set({ committedRangeNs: range, brushRangeNs: range }),
  setPlaying: (playing) => set({ playing }),
  setPlaybackRate: (rate) =>
    set({ playbackRate: Number.isFinite(rate) && rate > 0 ? rate : 1 }),
  setNominalRate: (rateHz) =>
    set({ nominalRateHz: rateHz !== null && Number.isFinite(rateHz) && rateHz > 0 ? rateHz : null }),
  selectEntity: (entityId) => set({ selectedEntityId: entityId }),
  hoverEntity: (entityId) => set({ hoveredEntityId: entityId }),
  hoverJoint: (jointId) => set({ hoveredJoint: jointId }),
  selectJoint: (jointId) => set({ selectedJoint: jointId }),
  focusPanel: (panel) => set({ focusedPanel: panel }),
  setInteracting: (interacting) => set({ interacting }),

  hydrate: (state) =>
    set((current) => ({
      committedTimeNs:
        state.committedTimeNs !== undefined ? state.committedTimeNs : current.committedTimeNs,
      committedRangeNs:
        state.committedRangeNs !== undefined ? state.committedRangeNs : current.committedRangeNs,
      selectedEntityId:
        state.selectedEntityId !== undefined ? state.selectedEntityId : current.selectedEntityId,
      focusedPanel: state.focusedPanel ?? current.focusedPanel,
      playheadNs:
        state.committedTimeNs !== undefined ? state.committedTimeNs : current.playheadNs,
    })),

  resetTransient: () => set({ ...TRANSIENT_DEFAULTS }),
}));

/** Read the effective time for a renderer: live playhead, else committed time. */
export function effectiveTimeNs(state: AnalysisState): bigint | null {
  return state.playheadNs ?? state.committedTimeNs;
}
