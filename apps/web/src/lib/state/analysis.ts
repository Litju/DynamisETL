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

export type PlaybackStatus = "idle" | "ready" | "buffering" | "ended";
export type PlaybackDirection = -1 | 1;

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
  playbackDirection: PlaybackDirection;
  /** Dense playback status; BUFFERING is explicit and blocks clock advance. */
  playbackStatus: PlaybackStatus;
  /** Nominal rate of the currently selected stream, for frame stepping. */
  nominalRateHz: number | null;
  selectedEntityId: string | null;
  hoveredEntityId: string | null;
  hoveredJoint: string | null;
  selectedJoint: string | null;
  focusedPanel: WorkbenchPanel;
  /** Renderer interaction flags (camera drag, pitch pan, chart drag). */
  interacting: boolean;
  /** A subject identity/time transition is in flight; renderers must not show stale data. */
  subjectSwitching: boolean;
  /** Previous Pose identity whose queries must stay retired during a switch. */
  switchingFromSubjectId: string | null;

  setPlayhead: (tNs: bigint | null) => void;
  commitTime: (tNs: bigint | null) => void;
  setHoverTime: (tNs: bigint | null) => void;
  setBrushRange: (range: TimeRangeNs | null) => void;
  commitRange: (range: TimeRangeNs | null) => void;
  setPlaying: (playing: boolean) => void;
  setPlaybackRate: (rate: number) => void;
  setPlaybackDirection: (direction: PlaybackDirection) => void;
  setPlaybackDirectionAndPlay: (direction: PlaybackDirection) => void;
  setPlaybackStatus: (status: PlaybackStatus) => void;
  setNominalRate: (rateHz: number | null) => void;
  selectEntity: (entityId: string | null) => void;
  hoverEntity: (entityId: string | null) => void;
  hoverJoint: (jointId: string | null) => void;
  selectJoint: (jointId: string | null) => void;
  focusPanel: (panel: WorkbenchPanel) => void;
  setInteracting: (interacting: boolean) => void;
  beginSubjectSwitch: (sourceSubjectId: string | null, targetTimeNs?: bigint) => void;
  finishSubjectSwitch: () => void;
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
  playbackStatus: "idle",
  nominalRateHz: null,
  hoveredEntityId: null,
  hoveredJoint: null,
  selectedJoint: null,
  interacting: false,
  subjectSwitching: false,
  switchingFromSubjectId: null,
} as const;

export const useAnalysisStore = create<AnalysisState>()((set) => ({
  ...TRANSIENT_DEFAULTS,
  committedTimeNs: null,
  committedRangeNs: null,
  playbackRate: 1,
  playbackDirection: 1,
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
  setPlaybackDirection: (playbackDirection) => set({ playbackDirection }),
  setPlaybackDirectionAndPlay: (playbackDirection) => set({ playbackDirection, playing: true }),
  setPlaybackStatus: (playbackStatus) => set({ playbackStatus }),
  setNominalRate: (rateHz) =>
    set({ nominalRateHz: rateHz !== null && Number.isFinite(rateHz) && rateHz > 0 ? rateHz : null }),
  selectEntity: (entityId) => set({ selectedEntityId: entityId }),
  hoverEntity: (entityId) => set({ hoveredEntityId: entityId }),
  hoverJoint: (jointId) => set({ hoveredJoint: jointId }),
  selectJoint: (jointId) => set({ selectedJoint: jointId }),
  focusPanel: (panel) => set({ focusedPanel: panel }),
  setInteracting: (interacting) => set({ interacting }),
  beginSubjectSwitch: (sourceSubjectId, targetTimeNs) =>
    set({
      ...(targetTimeNs !== undefined
        ? { playheadNs: targetTimeNs, committedTimeNs: targetTimeNs }
        : {}),
      hoverTimeNs: null,
      brushRangeNs: null,
      playing: false,
      playbackStatus: "idle",
      selectedEntityId: null,
      hoveredEntityId: null,
      hoveredJoint: null,
      selectedJoint: null,
      subjectSwitching: true,
      switchingFromSubjectId: sourceSubjectId,
    }),
  finishSubjectSwitch: () => set({ subjectSwitching: false, switchingFromSubjectId: null }),

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
