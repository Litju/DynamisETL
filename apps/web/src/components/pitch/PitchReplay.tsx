import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import {
  assignGroups,
  buildFrames,
  exactFrameIndex,
  isTrackingStream,
  summarizeFrame,
  teamRole,
  trailForRange,
  type EntityGroup,
  type TrackingFrame,
} from "@/components/pitch/pitch-model";
import {
  createPitchRenderer,
  DEFAULT_PITCH_LAYERS,
  type PitchEvent,
  type PitchLayers,
  type PitchPalette,
  type PitchRendererHandle,
} from "@/components/pitch/pitch-renderer";
import {
  EMPTY_INDEX,
  indexTacticalRows,
  tacticalOverlayAt,
  type TacticalFrameIndex,
} from "@/components/pitch/tactical-overlay";
import { eventStreams } from "@/lib/capabilities";
import type { ArtifactRef, DenseWindow, SessionDetail, StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import {
  artifactQuery,
  sessionQuery,
  tacticalArtifactsQuery,
  tacticalSeriesQuery,
  windowQuery,
  type WindowQuery,
} from "@/lib/api/queries";
import { readPalette } from "@/lib/chart-palette";
import { affordableSpanNs, canonicalSpan } from "@/lib/dense-window";
import type { DenseChunkBounds } from "@/lib/dense-chunks";
import {
  usePlaybackChunkCoordinator,
  type PlaybackChunkQueryOptions,
} from "@/lib/playback-chunk-coordinator";
import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";
import { useUiStore } from "@/lib/state/ui";
import { formatClockNs, formatDurationNs } from "@/lib/time";

const MAX_REPLAY_POINTS = 20_000;
const MAX_EVENT_POINTS = 2_000;
/**
 * Tactical series are read for the whole active chunk with a budget that keeps
 * them exact (the API's upper bound); a reduced response is never drawn.
 */
const TACTICAL_MAX_POINTS = 100_000;
/** Level C grids are emitted at most once per second (LEVEL-C-CONTRACT.md). */
const INFLUENCE_MAX_AGE_NS = 1_500_000_000;

/** Shape served event rows into renderer marks, dropping unplaceable ones. */
export function toPitchEvents(rows: ReadonlyArray<Record<string, unknown>>): PitchEvent[] {
  const events: PitchEvent[] = [];
  for (const row of rows) {
    const x = row["x_m"] ?? row["event_x_m"];
    const y = row["y_m"] ?? row["event_y_m"];
    const t = row["t_rel_ns"];
    // An event without a recorded location cannot be placed on the pitch, and
    // guessing one would invent spatial evidence the source does not hold.
    if (typeof x !== "number" || typeof y !== "number" || typeof t !== "number") continue;
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const type = row["event_type"];
    const subtype = row["event_subtype"];
    events.push({
      eventId: String(row["event_id"] ?? `${t}`),
      tRelNs: t,
      type: typeof type === "string" ? type : "event",
      subtype: typeof subtype === "string" ? subtype : null,
      xM: x,
      yM: y,
    });
  }
  return events;
}

/**
 * Session-stable team order and labels from the served participants: the two
 * provider team ids in sorted order (the same rule the markers always used),
 * labelled with the registered team name when the API serves one.
 */
export function sessionTeams(session: SessionDetail | undefined): {
  readonly order: readonly string[];
  readonly labels: ReadonlyMap<string, string>;
} {
  const labels = new Map<string, string>();
  for (const participant of session?.participants ?? []) {
    const groupId = participant.group_label;
    if (!groupId) continue;
    const name = (participant as { cohort?: string | null }).cohort;
    if (!labels.has(groupId) || (name && labels.get(groupId) === groupId)) {
      labels.set(groupId, name && name.length > 0 ? name : groupId);
    }
  }
  return { order: [...labels.keys()].sort(), labels };
}

/**
 * Field laboratory: PixiJS pitch replay over canonical tracking windows.
 * React owns the scene lifecycle and selection; the renderer owns frame-rate
 * updates (playhead subscription), so playback never triggers reconciliation.
 */
export function PitchReplay() {
  const context = useAnalysisContext();
  const datasetId = context?.datasetId ?? null;
  const sessionId = context?.sessionId ?? null;
  const streamId = context?.streamId ?? null;
  const queryClient = useQueryClient();

  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const stream: StreamView | null = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === streamId) ?? null;
  }, [session.data, streamId]);
  const teams = useMemo(() => sessionTeams(session.data), [session.data]);

  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const fromNs = context?.fromNs ?? null;
  const toNs = context?.toNs ?? null;

  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({
    ...artifactQuery(artifactId ?? ""),
    enabled: Boolean(artifactId),
  });

  // Replay needs exact entity frames, so the chunk span comes from the
  // artifact's measured density rather than a fixed duration that suits one
  // source. The coordinator changes the active query only at boundaries.
  const canonical = canonicalSpan(artifact.data);
  const chunkSpanNs = useMemo(
    () => affordableSpanNs(artifact.data, { maxPoints: MAX_REPLAY_POINTS }),
    [artifact.data],
  );
  const trackingRequest = useMemo<WindowQuery>(
    () => ({
      artifactId: artifactId ?? "",
      columns: [
        "t_rel_ns",
        "object_id",
        "object_type",
        "group_id",
        "x_m",
        "y_m",
        "is_detected",
      ],
      maxPoints: MAX_REPLAY_POINTS,
    }),
    [artifactId],
  );
  const queryOptionsFor = useCallback(
    (chunk: DenseChunkBounds): PlaybackChunkQueryOptions<DenseWindow> =>
      windowQuery({
        ...trackingRequest,
        fromNs: Number(chunk.fromNs),
        toNs: Number(chunk.toNs),
        cacheScope: "dense-chunk",
        chunkId: chunk.id,
      }) as unknown as PlaybackChunkQueryOptions<DenseWindow>,
    [trackingRequest],
  );
  const queryScope = useMemo(
    () => ({
      artifactId: trackingRequest.artifactId,
      columns: trackingRequest.columns?.join(",") ?? null,
      maxPoints: trackingRequest.maxPoints ?? null,
    }),
    [trackingRequest],
  );
  const explicitBounds = useMemo(
    () => (fromNs !== null && toNs !== null ? { fromNs, toNs } : null),
    [fromNs, toNs],
  );
  const isReady = useCallback(
    (data: DenseWindow | undefined) => data?.meta.reduction === null,
    [],
  );
  const matchesQuery = useCallback(
    (key: readonly unknown[]) =>
      key[0] === "dense-chunk" &&
      key[1] === queryScope.artifactId &&
      key[6] === queryScope.columns &&
      key[7] === queryScope.maxPoints &&
      key[8] === null,
    [queryScope],
  );
  const chunkIdFromQueryKey = useCallback(
    (key: readonly unknown[]) => (typeof key[3] === "string" ? key[3] : null),
    [],
  );
  const playback = usePlaybackChunkCoordinator<DenseWindow>({
    enabled: explicitBounds === null,
    canonicalMinNs: canonical?.minNs ?? null,
    canonicalMaxNs: canonical?.maxNs ?? null,
    chunkSpanNs,
    anchorNs: committedTimeNs,
    queryClient,
    queryOptionsFor,
    isReady,
    matchesQuery,
    chunkIdFromQueryKey,
  });
  const activeChunk = playback.plan?.active ?? null;
  const activeWindowBounds = activeChunk ?? explicitBounds;
  const activeQuery = useMemo(() => {
    if (activeChunk !== null) {
      return windowQuery({
        ...trackingRequest,
        fromNs: Number(activeChunk.fromNs),
        toNs: Number(activeChunk.toNs),
        cacheScope: "dense-chunk",
        chunkId: activeChunk.id,
      });
    }
    return windowQuery({
      ...trackingRequest,
      ...(explicitBounds !== null
        ? { fromNs: Number(explicitBounds.fromNs), toNs: Number(explicitBounds.toNs) }
        : {}),
    });
  }, [activeChunk, explicitBounds, trackingRequest]);
  // Discrete source events inside the same window. They are context for the
  // tracked frame, so an absent event stream simply means no marks, never an
  // error: SkillCorner publishes no event artifact for this session.
  const eventStream = useMemo(
    () => eventStreams(session.data?.streams ?? [])[0] ?? null,
    [session.data],
  );
  const eventArtifactId = eventStream?.sample_artifact_ids[0] ?? null;
  const eventWindow = useQuery({
    ...windowQuery({
      artifactId: eventArtifactId ?? "",
      ...(activeWindowBounds
        ? { fromNs: Number(activeWindowBounds.fromNs), toNs: Number(activeWindowBounds.toNs) }
        : {}),
      columns: ["t_rel_ns", "event_id", "event_type", "event_subtype", "x_m", "y_m"],
      maxPoints: MAX_EVENT_POINTS,
    }),
    enabled: Boolean(eventArtifactId) && activeWindowBounds !== null,
  });
  const events = useMemo(
    () => toPitchEvents(eventWindow.data?.rows ?? []),
    [eventWindow.data],
  );

  // The selection callback must be stable: the renderer is created once per
  // mount, and the durable context object changes on every URL commit.
  const selectEntityRef = useRef(context?.selectEntity);
  useEffect(() => {
    selectEntityRef.current = context?.selectEntity;
  }, [context?.selectEntity]);
  const handleSelectEntity = useCallback((objectId: string | null) => {
    useAnalysisStore.getState().selectEntity(objectId);
    selectEntityRef.current?.(objectId);
  }, []);

  const window = useQuery({
    ...activeQuery,
    // Keep the pitch mounted across a seek into a chunk that is still loading:
    // the previous window of the *same* artifact stays as placeholder while the
    // view states that exact frames are loading (no stale frame is drawn — the
    // exact-frame rule finds nothing for a time outside the placeholder).
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === (artifactId ?? "") ? previous : undefined,
    // The bounds come from the artifact, so the window waits for it rather
    // than firing an unbounded request for the whole recording first.
    enabled: Boolean(artifactId) && (explicitBounds !== null || activeChunk !== null),
  });

  if (!context) {
    return <StatePanel state="empty" title="Open a laboratory session first." />;
  }
  if (session.isPending) return <LoadingPanel label="Loading session streams" />;
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }
  if (streamId === null) {
    return (
      <StatePanel
        state="empty"
        title="No stream selected."
        detail="Select a tracking stream in the explorer to load the pitch replay."
      />
    );
  }
  if (stream === null) {
    return (
      <StatePanel
        state="unavailable"
        title="Stream is not part of this session."
        detail="Cross-session replay is never inferred."
      />
    );
  }
  if (!isTrackingStream(stream.modality)) {
    return (
      <StatePanel
        state="unavailable"
        title="This stream is not 2D tracking."
        detail={`The field laboratory renders tracking streams only; ${stream.stream_id} is ${stream.modality}.`}
      />
    );
  }
  if (artifactId === null) {
    return (
      <StatePanel
        state="unavailable"
        title="No canonical tracking artifact is registered."
        detail="Run the deterministic ingest path before replay."
      />
    );
  }
  if (artifact.isError || window.isError) {
    const error = artifact.error ?? window.error;
    if (error instanceof ApiError && error.state === "dense_window_too_large") {
      return (
        <StatePanel
          state="blocked"
          title="Replay window too large."
          detail="Narrow the range in the transport; spatial replay never decimates entity frames."
        />
      );
    }
    return (
      <ErrorPanel
        error={error}
        onRetry={() => {
          void artifact.refetch();
          void window.refetch();
        }}
      />
    );
  }
  if (artifact.isPending || activeWindowBounds === null || window.data === undefined) {
    return <LoadingPanel label="Loading tracking window" />;
  }
  if (window.data.meta.reduction !== null) {
    return (
      <StatePanel
        state="blocked"
        title="This window is display-reduced."
        detail="Replay requires exact entity frames; narrow from_ns/to_ns so the window fits the point budget."
      />
    );
  }
  return (
    <PitchView
      stream={stream}
      rows={window.data.rows}
      loadingWindow={window.isPlaceholderData}
      events={events}
      explicitRange={explicitBounds !== null}
      windowLabel={`${formatDurationNs(activeWindowBounds.toNs - activeWindowBounds.fromNs)} window`}
      playbackStatus={playback.status}
      tacticalBounds={activeWindowBounds}
      teamOrder={teams.order}
      teamLabels={teams.labels}
      onSelectEntity={handleSelectEntity}
    />
  );
}

/** A scene layer switch: pressed state carries text, a mark and border, not colour alone. */
function LayerToggle({
  label,
  pressed,
  onToggle,
  model = false,
  title,
}: {
  label: string;
  pressed: boolean;
  onToggle: () => void;
  model?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onToggle}
      title={title}
      className={
        pressed
          ? "t-control-compact inline-flex items-center gap-1 rounded-control border border-accent bg-surface-3 px-2 text-[11px] text-text-primary"
          : "t-control-compact inline-flex items-center gap-1 rounded-control border border-border-subtle px-2 text-[11px] text-text-muted transition-colors duration-quick hover:border-border-strong hover:text-text-secondary"
      }
    >
      <span aria-hidden="true" className="w-2 text-center text-[10px]">{pressed ? "✓" : ""}</span>
      {label}
      {model ? (
        <span className="rounded-[2px] border border-measurement-model-estimated/60 px-0.5 text-[9px] uppercase tracking-wide text-measurement-model-estimated">
          model
        </span>
      ) : null}
    </button>
  );
}

function seriesArtifact(artifacts: readonly ArtifactRef[] | undefined, seriesName: string): ArtifactRef | null {
  return artifacts?.find((artifact) => artifact.artifact_metadata?.series_name === seriesName) ?? null;
}

function readTeamPalette(): { teamA: string; teamB: string; halo: string } {
  if (typeof document === "undefined") return { teamA: "#8fc7ef", teamB: "#f0b454", halo: "#111418" };
  const styles = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
  return {
    teamA: read("--d-team-a", "#8fc7ef"),
    teamB: read("--d-team-b", "#f0b454"),
    halo: read("--d-team-halo", "#111418"),
  };
}

function PitchView({
  stream,
  rows,
  loadingWindow,
  events,
  explicitRange,
  windowLabel,
  playbackStatus,
  tacticalBounds,
  teamOrder,
  teamLabels,
  onSelectEntity,
}: {
  stream: StreamView;
  rows: Array<Record<string, unknown>>;
  loadingWindow: boolean;
  events: readonly PitchEvent[];
  explicitRange: boolean;
  windowLabel: string;
  playbackStatus: "idle" | "ready" | "buffering" | "ended";
  tacticalBounds: { readonly fromNs: bigint; readonly toNs: bigint };
  teamOrder: readonly string[];
  teamLabels: ReadonlyMap<string, string>;
  onSelectEntity: (objectId: string | null) => void;
}) {
  const context = useAnalysisContext();
  const theme = useUiStore((state) => state.theme);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<PitchRendererHandle | null>(null);
  const selectedEntityId = useAnalysisStore((state) => state.selectedEntityId);
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);
  const [rendererReady, setRendererReady] = useState(false);
  const [layers, setLayers] = useState<PitchLayers>(DEFAULT_PITCH_LAYERS);
  const [influenceGridTimeNs, setInfluenceGridTimeNs] = useState<number | null>(null);

  const frames = useMemo(
    () =>
      buildFrames(
        rows as Array<{
          t_rel_ns?: unknown;
          object_id?: unknown;
          object_type?: unknown;
          group_id?: unknown;
          x_m?: unknown;
          y_m?: unknown;
          is_detected?: unknown;
        }>,
      ),
    [rows],
  );
  const groups = useMemo(() => assignGroups(frames, teamOrder), [frames, teamOrder]);
  const maxGapNs = useMemo(
    () => 1.5 * (1e9 / (stream.nominal_sampling_rate_hz && stream.nominal_sampling_rate_hz > 0 ? stream.nominal_sampling_rate_hz : 25)),
    [stream.nominal_sampling_rate_hz],
  );

  const tacticalArtifacts = useQuery({
    ...tacticalArtifactsQuery({
      datasetId: context?.datasetId ?? "",
      sessionId: context?.sessionId,
      streamId: stream.stream_id,
    }),
    enabled: Boolean(context?.datasetId && context?.sessionId),
  });
  const teamArtifact = seriesArtifact(tacticalArtifacts.data, "team_geometry");
  const territoryArtifact = seriesArtifact(tacticalArtifacts.data, "player_territory");
  const influenceArtifact = seriesArtifact(tacticalArtifacts.data, "influence_grid");
  const tacticalWindow = (artifactId: string | null) => tacticalSeriesQuery({
    artifactId: artifactId ?? "",
    fromNs: Number(tacticalBounds.fromNs),
    toNs: Number(tacticalBounds.toNs),
    maxPoints: TACTICAL_MAX_POINTS,
  });
  const teamTactical = useQuery({
    ...tacticalWindow(teamArtifact?.artifact_id ?? null),
    enabled: Boolean(teamArtifact && layers.geometry),
  });
  const territoryTactical = useQuery({
    ...tacticalWindow(territoryArtifact?.artifact_id ?? null),
    enabled: Boolean(territoryArtifact && layers.territory),
  });
  const influenceTactical = useQuery({
    ...tacticalWindow(influenceArtifact?.artifact_id ?? null),
    enabled: Boolean(influenceArtifact && layers.influence),
  });
  // A display-reduced tactical response is a subset of frames; it is never
  // drawn as if it were the current geometry.
  const exactRows = (data: { rows: unknown[]; meta: { returned_rows: number; source_rows: number } } | undefined) =>
    data && data.meta.returned_rows === data.meta.source_rows ? (data.rows as Record<string, unknown>[]) : null;
  // A hidden layer contributes nothing to the drawn overlay.
  const geometryRows = layers.geometry ? exactRows(teamTactical.data) : null;
  const territoryRows = layers.territory ? exactRows(territoryTactical.data) : null;
  const influenceRows = layers.influence ? exactRows(influenceTactical.data) : null;
  const reducedOverlay =
    (layers.geometry && teamTactical.data !== undefined && geometryRows === null) ||
    (layers.territory && territoryTactical.data !== undefined && territoryRows === null) ||
    (layers.influence && influenceTactical.data !== undefined && influenceRows === null);
  const indexes = useMemo(
    () => ({
      geometry: geometryRows ? indexTacticalRows(geometryRows) : EMPTY_INDEX,
      territory: territoryRows ? indexTacticalRows(territoryRows) : EMPTY_INDEX,
      influence: influenceRows ? indexTacticalRows(influenceRows) : EMPTY_INDEX,
    }),
    [geometryRows, territoryRows, influenceRows],
  );

  const palette = useMemo<PitchPalette>(() => {
    void theme;
    const tokens = readPalette();
    const team = readTeamPalette();
    return {
      surface: tokens.surface,
      pitchLine: tokens.grid,
      home: team.teamA,
      away: team.teamB,
      ball: tokens.text,
      official: tokens.measurement.PIPELINE_DERIVED ?? tokens.series[2]!,
      extrapolated: tokens.textMuted,
      selection: tokens.playhead,
      trail: tokens.axis,
      label: tokens.textMuted,
      event: tokens.measurement.SOURCE_DERIVED ?? tokens.warning,
      halo: team.halo,
    };
  }, [theme]);

  // Everything the imperative renderer reads lives in refs, so the renderer is
  // created once per mount (and per theme), never per window or per frame.
  const sceneRef = useRef<{
    frames: readonly TrackingFrame[];
    groups: ReadonlyMap<string, EntityGroup>;
    indexes: { geometry: TacticalFrameIndex; territory: TacticalFrameIndex; influence: TacticalFrameIndex };
    teamOrder: readonly string[];
    maxGapNs: number;
    layers: PitchLayers;
    events: readonly PitchEvent[];
    drawnFrameTime: number | null | undefined;
    influenceGridTimeNs: number | null;
  }>({
    frames,
    groups,
    indexes,
    teamOrder,
    maxGapNs,
    layers: DEFAULT_PITCH_LAYERS,
    events,
    drawnFrameTime: undefined,
    influenceGridTimeNs: null,
  });

  const drawAt = useCallback((timeNs: bigint | null, force = false) => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    const scene = sceneRef.current;
    const index = exactFrameIndex(scene.frames, timeNs, scene.maxGapNs);
    const frame = index >= 0 ? scene.frames[index]! : null;
    const frameTime = frame?.tRelNs ?? null;
    if (!force && frameTime === scene.drawnFrameTime) return;
    scene.drawnFrameTime = frameTime;
    const selected = useAnalysisStore.getState().selectedEntityId;
    renderer.setFrame(frame?.entities ?? [], scene.groups, selected);
    const overlay = tacticalOverlayAt(
      scene.indexes,
      frameTime,
      (groupId) => teamRole(groupId, scene.teamOrder),
      INFLUENCE_MAX_AGE_NS,
    );
    scene.influenceGridTimeNs = overlay.influenceGridTimeNs;
    renderer.setTacticalOverlay(overlay.overlay);
    // Machine-readable evidence of what the canvas shows: the drawn entity
    // frame and the overlay's frame are the same canonical time by construction.
    const host = hostRef.current;
    if (host) {
      host.dataset.drawnFrameNs = frameTime === null ? "" : String(frameTime);
      host.dataset.overlayHulls = String(overlay.overlay.hulls.length);
      host.dataset.overlayTerritoryCells = String(overlay.overlay.territoryCells.length);
      host.dataset.overlayInfluenceCells = String(overlay.overlay.influenceCells.length);
    }
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let renderer: PitchRendererHandle | null = null;
    setRendererReady(false);
    void createPitchRenderer(host, palette, (objectId) => onSelectEntity(objectId)).then((created) => {
      if (disposed) {
        created.destroy();
        return;
      }
      renderer = created;
      rendererRef.current = created;
      created.setLayers(sceneRef.current.layers);
      created.setEvents(sceneRef.current.events);
      const current = useAnalysisStore.getState();
      created.setTrail(
        trailForRange(sceneRef.current.frames, current.committedRangeNs, current.selectedEntityId),
        sceneRef.current.groups,
        current.selectedEntityId,
      );
      drawAt(effectiveTimeNs(current), true);
      setRendererReady(true);
    });
    return () => {
      disposed = true;
      setRendererReady(false);
      renderer?.destroy();
      rendererRef.current = null;
    };
  }, [drawAt, onSelectEntity, palette]);

  // New window / tactical data / team order: update the scene and redraw the
  // current frame imperatively.
  useEffect(() => {
    const scene = sceneRef.current;
    scene.frames = frames;
    scene.groups = groups;
    scene.indexes = indexes;
    scene.teamOrder = teamOrder;
    scene.maxGapNs = maxGapNs;
    drawAt(effectiveTimeNs(useAnalysisStore.getState()), true);
    setInfluenceGridTimeNs(scene.influenceGridTimeNs);
  }, [drawAt, frames, groups, indexes, maxGapNs, teamOrder]);

  // Per-frame path: a store subscription, never a React render.
  useEffect(() => {
    return useAnalysisStore.subscribe((state, previous) => {
      const next = effectiveTimeNs(state);
      if (next !== effectiveTimeNs(previous)) drawAt(next);
      if (state.selectedEntityId !== previous.selectedEntityId) drawAt(next, true);
    });
  }, [drawAt]);

  useEffect(() => {
    rendererRef.current?.setTrail(
      trailForRange(frames, committedRangeNs, selectedEntityId),
      groups,
      selectedEntityId,
    );
  }, [committedRangeNs, frames, groups, selectedEntityId]);

  // Layer visibility is renderer-local presentation state: it changes nothing
  // about the data and never belongs in the durable URL.
  useEffect(() => {
    sceneRef.current.layers = layers;
    rendererRef.current?.setLayers(layers);
  }, [layers]);
  useEffect(() => {
    sceneRef.current.events = events;
    rendererRef.current?.setEvents(events);
  }, [events]);

  const [, bumpHeader] = useReducer((value: number) => value + 1, 0);
  useEffect(() => {
    let lastEmit = 0;
    return useAnalysisStore.subscribe((state, previous) => {
      const next = effectiveTimeNs(state);
      if (next === effectiveTimeNs(previous) && state.selectedEntityId === previous.selectedEntityId) return;
      // The DOM summary is a low-frequency text alternative, not a per-frame
      // render: it updates at most five times per second during playback.
      const now = performance.now();
      if (now - lastEmit < 200) return;
      lastEmit = now;
      setInfluenceGridTimeNs(sceneRef.current.influenceGridTimeNs);
      bumpHeader();
    });
  }, []);

  const currentTimeNs = effectiveTimeNs(useAnalysisStore.getState());
  const currentFrameIndex = exactFrameIndex(frames, currentTimeNs, maxGapNs);
  const currentFrame = currentFrameIndex >= 0 ? frames[currentFrameIndex]! : null;
  const summary = summarizeFrame(currentFrame);
  const selectedEntity =
    selectedEntityId === null
      ? null
      : (currentFrame?.entities.find((entity) => entity.objectId === selectedEntityId) ?? null);
  const teamLabel = (groupId: string | null) =>
    groupId === null ? null : (teamLabels.get(groupId) ?? groupId);
  const tacticalLoading =
    (layers.geometry && teamTactical.isFetching) ||
    (layers.territory && territoryTactical.isFetching) ||
    (layers.influence && influenceTactical.isFetching);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-2">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 className="t-analysis-title">
            Pitch tracking
            <span className="ml-2 text-[12px] font-normal text-text-muted">
              {explicitRange ? "selected range" : windowLabel}
            </span>
          </h2>
          <div className="flex items-center gap-2 text-[11px] text-text-muted">
            <ModalityBadge modality={stream.modality} />
            <MeasurementClassBadge measurementClass={stream.measurement_class} compact />
            <span className="tabular">
              {stream.nominal_sampling_rate_hz !== null
                ? `${stream.nominal_sampling_rate_hz} Hz`
                : "rate unknown"}
            </span>
            {playbackStatus === "buffering" ? (
              <span data-testid="playback-buffering" className="text-quality-warning">BUFFERING</span>
            ) : null}
          </div>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted">
          <span className="tabular" data-testid="pitch-frame-summary">
            {summary === null
              ? loadingWindow
                ? "Loading exact frames for this time…"
                : "No tracking frame at this time"
              : `${summary.players} players · ${summary.extrapolated} extrapolated`}
          </span>
          <span className="tabular">
            {summary === null
              ? "—"
              : `Ball ${summary.ballDetected === null ? "detection unknown" : summary.ballDetected ? "detected" : "extrapolated"}`}
          </span>
          {events.length > 0 ? (
            <span className="tabular">{events.length} source events in window</span>
          ) : null}
          <div role="group" aria-label="Scene layers" className="ml-auto flex flex-wrap items-center gap-1">
            <LayerToggle
              label="Trails"
              pressed={layers.trails}
              onToggle={() => setLayers((current) => ({ ...current, trails: !current.trails }))}
            />
            <LayerToggle
              label="Labels"
              pressed={layers.labels}
              onToggle={() => setLayers((current) => ({ ...current, labels: !current.labels }))}
            />
            {events.length > 0 ? (
              <LayerToggle
                label="Events"
                pressed={layers.events}
                onToggle={() => setLayers((current) => ({ ...current, events: !current.events }))}
              />
            ) : null}
            {teamArtifact ? (
              <LayerToggle
                label="Hull"
                title="Level A convex hull per team at the current frame (deterministic)"
                pressed={layers.geometry}
                onToggle={() => setLayers((current) => ({ ...current, geometry: !current.geometry }))}
              />
            ) : null}
            {territoryArtifact ? (
              <LayerToggle
                label="Territory"
                title="Level B clipped Voronoi territory at the current frame (deterministic geometry)"
                pressed={layers.territory}
                onToggle={() => setLayers((current) => ({ ...current, territory: !current.territory }))}
              />
            ) : null}
            {influenceArtifact ? (
              <LayerToggle
                label="Influence"
                model
                title="Level C arrival-time influence grid (MODEL_ESTIMATED, sampled ≤ 1 Hz)"
                pressed={layers.influence}
                onToggle={() => setLayers((current) => ({ ...current, influence: !current.influence }))}
              />
            ) : null}
            <button
              type="button"
              onClick={() => rendererRef.current?.resetView()}
              title="Frame the whole pitch again"
              className="t-control-compact rounded-control border border-border-subtle px-2 text-[11px] text-text-muted transition-colors duration-quick hover:border-border-strong hover:text-text-secondary"
            >
              Reset view
            </button>
          </div>
        </div>
      </header>
      <div className="relative min-h-0 flex-1">
        <div
          ref={hostRef}
          role="img"
          aria-label={
            summary === null
              ? `Pitch replay for ${stream.stream_id}: no tracking frame at ${currentTimeNs === null ? "the current time" : formatClockNs(currentTimeNs)}`
              : `Pitch replay for ${stream.stream_id} at ${formatClockNs(BigInt(summary.tRelNs))}: ${summary.players} players, ball ${summary.ballDetected === false ? "extrapolated" : "tracked"}`
          }
          data-testid="pitch-canvas"
          data-renderer="pixi"
          data-renderer-ready={rendererReady ? "true" : "false"}
          data-frame-ns={summary === null ? "" : String(summary.tRelNs)}
          className="h-full w-full"
        />
        {loadingWindow || tacticalLoading ? (
          <div
            role="status"
            className="pointer-events-none absolute right-2 top-2 rounded-control border border-border-subtle bg-surface-1/90 px-2 py-1 text-[11px] text-text-muted"
          >
            {loadingWindow ? "Loading exact tracking frames…" : "Loading tactical overlay…"}
          </div>
        ) : null}
        <div data-testid="pitch-selection" className="pointer-events-none absolute left-2 top-2 max-w-72 rounded-control border border-border-subtle bg-surface-1/90 px-2 py-1 text-[11px]">
          {selectedEntity ? (
            <>
              <div className="text-text-primary">
                {selectedEntity.isBall ? "Ball" : (teamLabel(selectedEntity.groupId) ?? "Unassigned")}
                <span className="mono ml-1.5 text-text-muted">{selectedEntity.objectId}</span>
              </div>
              <div className="mono text-text-muted">
                x {selectedEntity.xM.toFixed(2)} m · y {selectedEntity.yM.toFixed(2)} m
              </div>
              <div className="text-text-muted">
                {selectedEntity.detected === false ? "extrapolated position" : "detected position"}
              </div>
            </>
          ) : selectedEntityId !== null ? (
            <span className="text-text-muted">
              <span className="mono">{selectedEntityId}</span> is not tracked in this frame.
            </span>
          ) : (
            <span className="text-text-muted">
              Select a player or the ball on the pitch; entities are never fused across groups.
            </span>
          )}
        </div>
        <div className="pointer-events-none absolute bottom-2 left-2 rounded-control border border-border-subtle bg-surface-1/90 px-2 py-1 text-[10px] text-text-muted">
          {summary === null ? "—" : formatClockNs(BigInt(summary.tRelNs))} · wheel zoom, drag pan
        </div>
        {reducedOverlay ? (
          <div role="status" className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded-control border border-quality-warning/60 bg-surface-1/95 px-2 py-1 text-[11px] text-quality-warning">
            Tactical overlay withheld: the window was display-reduced and is not the exact frame.
          </div>
        ) : null}
        {selectedEntityId !== null ? (
          <button
            type="button"
            onClick={() => onSelectEntity(null)}
            className="t-control-compact absolute bottom-2 right-2 rounded-control border border-border-subtle bg-surface-1/90 px-2 text-[10px] text-text-muted hover:border-border-strong"
            title="Clear the current selection"
          >
            clear selection: <span className="mono">{selectedEntityId}</span>
          </button>
        ) : null}
      </div>
      <footer className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle bg-surface-1 px-4 py-1.5 text-[10px] text-text-muted">
        {teamOrder.slice(0, 2).map((groupId, index) => (
          <span key={groupId} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block size-2 rounded-full"
              style={{ backgroundColor: index === 0 ? "var(--d-team-a)" : "var(--d-team-b)" }}
            />
            <span className="text-text-secondary">{teamLabel(groupId)}</span>
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block size-2 rounded-full bg-text-muted" />
          Detected (filled)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block size-2 rounded-full border border-text-muted" />
          Extrapolated (hollow)
        </span>
        {events.length > 0 ? (
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block size-2 rotate-45 border"
              style={{ borderColor: "var(--d-measurement-source-derived)" }}
            />
            Source event
          </span>
        ) : null}
        {teamArtifact && layers.geometry ? <span>Hull: deterministic outline, current frame</span> : null}
        {territoryArtifact && layers.territory ? <span>Territory: clipped Voronoi, current frame</span> : null}
        {influenceArtifact && layers.influence ? (
          <span>
            Influence: MODEL_ESTIMATED tiles
            {influenceGridTimeNs !== null ? ` · grid @ ${formatClockNs(BigInt(influenceGridTimeNs))}` : " · no grid within 1.5 s"}
          </span>
        ) : null}
        <span>Trails: committed range</span>
        <span className="mono ml-auto tabular">
          frame {currentFrameIndex >= 0 ? currentFrameIndex + 1 : "—"} / {frames.length}
        </span>
      </footer>
    </div>
  );
}
