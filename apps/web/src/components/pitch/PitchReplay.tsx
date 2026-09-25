import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import {
  isTrackingStream,
  sessionTeams,
  teamRole,
} from "@/components/pitch/pitch-model";
import {
  trackingEntityAt,
  trackingFrameIndexAt,
  trackingFrameSummaryAt,
  tacticalOverlayAtBuffers,
  trailPointsForTrackingBuffer,
} from "@/components/matchlab/frame-buffers";
import type {
  EventWindowBuffers,
  TacticalGridWindowBuffers,
  TacticalPolygonWindowBuffers,
  TrackingWindowBuffers,
} from "@/components/matchlab/frame-buffers";
import { indexTacticalV3Frame } from "@/components/pitch/tactical-v3";
import type { TacticalRow } from "@/components/pitch/tactical-overlay";
import {
  type PitchPalette,
  type PitchRendererHandle,
} from "@/components/pitch/pitch-renderer-types";
import {
  DEFAULT_PITCH_LAYERS,
  type PitchEvent,
  type PitchLayers,
} from "@/components/matchlab/render-types";
import { FieldSceneView, type FieldCameraMode, type FieldSceneViewHandle } from "@/components/pitch/FieldSceneView";
import { eventStreams } from "@/lib/capabilities";
import type { ArtifactRef, SessionDetail, StreamView, TacticalSeriesView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useMatchFrameContext } from "@/lib/match-frame-context";
import { ApiError } from "@/lib/api/client";
import {
  eventFrameWindowQuery,
  tacticalGridWindowQuery,
  tacticalPolygonWindowQuery,
  trackingFrameWindowQuery,
} from "@/lib/api/match-frame-windows";
import type {
  PreparedTacticalGridWindow,
  PreparedTacticalPolygonWindow,
  PreparedTrackingWindow,
} from "@/lib/api/match-frame-windows";
import {
  artifactQuery,
  sessionQuery,
  tacticalArtifactsQuery,
  tacticalSeriesQuery,
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

export { sessionTeams };

const MAX_REPLAY_POINTS = 20_000;
const MAX_EVENT_POINTS = 2_000;
/**
 * Tactical series are read for the whole active chunk with a budget that keeps
 * them exact (the API's upper bound); a reduced response is never drawn.
 */
const TACTICAL_MAX_POINTS = 100_000;
const V3_BUCKET_NS = 30_000_000_000n;
const V3_LOOKBACK_NS = 2_000_000_000n;
/** Level C grids are emitted at most once per second (LEVEL-C-CONTRACT.md). */
const INFLUENCE_MAX_AGE_NS = 1_500_000_000;
const HULL_COLUMNS = ["t_rel_ns", "group_id", "hull_polygon_json"] as const;
const TERRITORY_COLUMNS = ["t_rel_ns", "entity_id", "group_id", "cell_polygon_json"] as const;
const INFLUENCE_COLUMNS = ["t_rel_ns", "x_m", "y_m", "owner_group_id", "arrival_time_s"] as const;

function exactV3Rows(data: TacticalSeriesView | undefined): TacticalRow[] {
  return data && data.meta.returned_rows === data.meta.source_rows ? data.rows as TacticalRow[] : [];
}
const EMPTY_POLYGONS: TacticalPolygonWindowBuffers = {
  frameTimesNs: new BigInt64Array(),
  framePolygonOffsets: new Uint32Array([0]),
  polygonPointOffsets: new Uint32Array([0]),
  positionsXY: new Float32Array(),
  objectIds: [],
  objectIndexes: new Uint32Array(),
  groupIds: [],
  groupIndexes: new Int32Array(),
};
const EMPTY_GRID: TacticalGridWindowBuffers = {
  gridTimesNs: new BigInt64Array(),
  gridOffsets: new Uint32Array([0]),
  positionsXY: new Float32Array(),
  values: new Float32Array(),
  groupIds: [],
  groupIndexes: new Int32Array(),
  cellWidthM: new Float32Array(),
  cellHeightM: new Float32Array(),
};

function pixiParityOracleEnabled(): boolean {
  return (import.meta.env.DEV || import.meta.env.MODE === "test") && typeof window !== "undefined" &&
    window.localStorage.getItem("dynamis-matchlab-pixi-parity") === "1";
}

function loadPixiPitchRenderer() {
  if (import.meta.env.MODE === "test") return import("@/components/pitch/pitch-renderer");
  const moduleUrl = new URL("/src/components/pitch/pitch-renderer.ts", window.location.origin).href;
  return import(/* @vite-ignore */ moduleUrl);
}

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

/** The worker filters unplaceable events and transfers the numeric columns. */
export function pitchEventsFromBuffers(buffers: EventWindowBuffers | undefined): PitchEvent[] {
  if (buffers === undefined) return [];
  return Array.from(buffers.timeNs, (timeNs, index) => ({
    eventId: buffers.eventIds[index] ?? "",
    tRelNs: Number(timeNs),
    type: buffers.eventTypes[index] ?? "event",
    subtype: buffers.eventSubtypes[index] ?? null,
    xM: buffers.positionsXY[index * 2] ?? Number.NaN,
    yM: buffers.positionsXY[index * 2 + 1] ?? Number.NaN,
  }));
}

/**
 * On-pitch labels: the registered shirt number when the provider registered
 * one (`shirt 16 (…)` → `16`), otherwise the renderer's short id.
 */
export function shirtLabels(session: SessionDetail | undefined): ReadonlyMap<string, string> {
  const labels = new Map<string, string>();
  for (const participant of session?.participants ?? []) {
    const match = /^shirt\s+(\d+)(?!\d)/i.exec(participant.notes ?? "");
    if (match) labels.set(participant.subject_id, match[1]!);
  }
  return labels;
}

/**
 * Field laboratory over exact canonical windows. R3F is the production view;
 * Pixi remains reachable only as a development parity oracle.
 */
export function PitchReplay() {
  const context = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
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
  const entityLabels = useMemo(() => shirtLabels(session.data), [session.data]);

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
    (chunk: DenseChunkBounds): PlaybackChunkQueryOptions<PreparedTrackingWindow> =>
      trackingFrameWindowQuery({
        ...trackingRequest,
        fromNs: Number(chunk.fromNs),
        toNs: Number(chunk.toNs),
        cacheScope: "dense-chunk",
        chunkId: chunk.id,
      }) as unknown as PlaybackChunkQueryOptions<PreparedTrackingWindow>,
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
    (data: PreparedTrackingWindow | undefined) => data?.meta.reduction === null,
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
  const playback = usePlaybackChunkCoordinator<PreparedTrackingWindow>({
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
      return trackingFrameWindowQuery({
        ...trackingRequest,
        fromNs: Number(activeChunk.fromNs),
        toNs: Number(activeChunk.toNs),
        cacheScope: "dense-chunk",
        chunkId: activeChunk.id,
      });
    }
    return trackingFrameWindowQuery({
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
  const eventRequest = useMemo<WindowQuery>(
    () => ({
      artifactId: eventArtifactId ?? "",
      ...(activeWindowBounds
        ? { fromNs: Number(activeWindowBounds.fromNs), toNs: Number(activeWindowBounds.toNs) }
        : {}),
      columns: ["t_rel_ns", "event_id", "event_type", "event_subtype", "x_m", "y_m"],
      maxPoints: MAX_EVENT_POINTS,
    }),
    [activeWindowBounds, eventArtifactId],
  );
  const eventWindow = useQuery({
    ...eventFrameWindowQuery(eventRequest),
    enabled: Boolean(eventArtifactId) && activeWindowBounds !== null,
  });
  const events = useMemo(
    () => pitchEventsFromBuffers(eventWindow.data?.prepared),
    [eventWindow.data],
  );

  // The selection callback stays stable while the renderer is mounted; the
  // context action itself follows the latest durable URL state.
  const matchFrameRef = useRef(matchFrame);
  const selectFieldEntityRef = useRef(context?.selectFieldEntity);
  useEffect(() => {
    matchFrameRef.current = matchFrame;
  }, [matchFrame]);
  useEffect(() => {
    selectFieldEntityRef.current = context?.selectFieldEntity;
  }, [context?.selectFieldEntity]);
  const handleSelectEntity = useCallback((objectId: string | null, objectType?: string | null) => {
    if (matchFrameRef.current) {
      matchFrameRef.current.selectTrackingObject(objectId, objectType);
    } else {
      selectFieldEntityRef.current?.(objectId);
    }
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
      trackingBuffers={window.data.prepared}
      loadingWindow={window.isPlaceholderData}
      events={events}
      explicitRange={explicitBounds !== null}
      windowLabel={`${formatDurationNs(activeWindowBounds.toNs - activeWindowBounds.fromNs)} window`}
      playbackStatus={playback.status}
      tacticalBounds={activeWindowBounds}
      teamOrder={teams.order}
      teamLabels={teams.labels}
      entityLabels={entityLabels}
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

function currentV3Window(timeNs: bigint | null): { readonly fromNs: bigint; readonly toNs: bigint } | null {
  if (timeNs === null) return null;
  const bucket = timeNs >= 0n ? timeNs / V3_BUCKET_NS : (timeNs - V3_BUCKET_NS + 1n) / V3_BUCKET_NS;
  const start = bucket * V3_BUCKET_NS;
  return { fromNs: start - V3_LOOKBACK_NS, toNs: start + V3_BUCKET_NS - 1n };
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

function oklchToHex(value: string): string | null {
  const match = /^oklch\(\s*([\d.]+)(%)?\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*\)$/i.exec(value);
  if (!match) return null;
  const lightness = Number(match[1]) / (match[2] ? 100 : 1);
  const chroma = Number(match[3]);
  const hue = Number(match[4]) * Math.PI / 180;
  const a = chroma * Math.cos(hue);
  const b = chroma * Math.sin(hue);
  const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const channels = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s,
  ].map((linear) => {
    const srgb = linear <= 0.0031308 ? 12.92 * linear : 1.055 * linear ** (1 / 2.4) - 0.055;
    return Math.round(Math.max(0, Math.min(1, srgb)) * 255).toString(16).padStart(2, "0");
  });
  return "#" + channels.join("");
}

function PitchView({
  stream,
  trackingBuffers,
  loadingWindow,
  events,
  explicitRange,
  windowLabel,
  playbackStatus,
  tacticalBounds,
  teamOrder,
  teamLabels,
  entityLabels,
  onSelectEntity,
}: {
  stream: StreamView;
  trackingBuffers: TrackingWindowBuffers;
  loadingWindow: boolean;
  events: readonly PitchEvent[];
  explicitRange: boolean;
  windowLabel: string;
  playbackStatus: "idle" | "ready" | "buffering" | "ended";
  tacticalBounds: { readonly fromNs: bigint; readonly toNs: bigint };
  teamOrder: readonly string[];
  teamLabels: ReadonlyMap<string, string>;
  entityLabels: ReadonlyMap<string, string>;
  onSelectEntity: (objectId: string | null, objectType?: string | null) => void;
}) {
  const context = useAnalysisContext();
  const theme = useUiStore((state) => state.theme);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<PitchRendererHandle | null>(null);
  const fieldSceneRef = useRef<FieldSceneViewHandle | null>(null);
  const pixiParityOracle = useMemo(() => pixiParityOracleEnabled(), []);
  const matchFrame = useMatchFrameContext();
  const matchFrameRef = useRef(matchFrame);
  useEffect(() => {
    matchFrameRef.current = matchFrame;
  }, [matchFrame]);
  const selectedEntityId =
    matchFrame?.selectedTrackingObjectId ?? context?.subjectId ?? context?.entityId ?? null;
  const selectedEntityRef = useRef(selectedEntityId);
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);
  // PitchView already throttles playhead-driven DOM/query work to 5 Hz; keep
  // tactical window keys bucketed without adding a per-source-frame React subscription.
  const v3TimeNs = effectiveTimeNs(useAnalysisStore.getState());
  const tacticalRelationMode = useAnalysisStore((state) => state.tacticalRelationMode);
  const scalarFieldMode = useAnalysisStore((state) => state.scalarFieldMode);
  const [rendererReady, setRendererReady] = useState(false);
  const [layers, setLayers] = useState<PitchLayers>(DEFAULT_PITCH_LAYERS);
  const [cameraMode, setCameraMode] = useState<FieldCameraMode>("tactical-map");
  const [influenceGridTimeNs, setInfluenceGridTimeNs] = useState<bigint | null>(null);
  const handleInfluenceGridTime = useCallback((timeNs: bigint | null) => {
    setInfluenceGridTimeNs((current) => current === timeNs ? current : timeNs);
  }, []);
  const handleSceneReady = useCallback(() => setRendererReady(true), []);

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
  const unitsArtifact = seriesArtifact(tacticalArtifacts.data, "functional_unit_geometry");
  const edgesArtifact = seriesArtifact(tacticalArtifacts.data, "shape_graph_edges");
  const trianglesArtifact = seriesArtifact(tacticalArtifacts.data, "tactical_triangles");
  const interactionsArtifact = seriesArtifact(tacticalArtifacts.data, "attacker_defender_interactions");
  const possessionArtifact = seriesArtifact(tacticalArtifacts.data, "source_possession_context");
  const v3Bounds = currentV3Window(v3TimeNs);
  const v3Query = (artifact: ArtifactRef | null, enabled: boolean) => ({
    ...tacticalSeriesQuery({
      artifactId: artifact?.artifact_id ?? "",
      fromNs: v3Bounds ? Number(v3Bounds.fromNs) : undefined,
      toNs: v3Bounds ? Number(v3Bounds.toNs) : undefined,
      maxPoints: TACTICAL_MAX_POINTS,
    }),
    enabled: Boolean(artifact && v3Bounds && enabled),
  });
  const fieldUnits = useQuery(v3Query(unitsArtifact, true));
  const fieldEdges = useQuery(v3Query(edgesArtifact, tacticalRelationMode === "stable-graph" && (selectedEntityId !== null || Boolean(matchFrame?.selectedTeamId))));
  const fieldTriangles = useQuery(v3Query(trianglesArtifact, tacticalRelationMode === "selected-triangles" && selectedEntityId !== null));
  const fieldInteractions = useQuery(v3Query(interactionsArtifact, tacticalRelationMode === "attacker-defender" && selectedEntityId !== null));
  const fieldPossession = useQuery(v3Query(possessionArtifact, true));
  const v3Reduced = [fieldUnits.data, fieldPossession.data, fieldEdges.data, fieldTriangles.data, fieldInteractions.data]
    .some((data) => data !== undefined && data.meta.returned_rows !== data.meta.source_rows);
  const tacticalV3Index = useMemo(() => indexTacticalV3Frame({
    units: exactV3Rows(fieldUnits.data),
    edges: exactV3Rows(fieldEdges.data),
    triangles: exactV3Rows(fieldTriangles.data),
    interactions: exactV3Rows(fieldInteractions.data),
    possession: exactV3Rows(fieldPossession.data),
  }), [fieldEdges.data, fieldInteractions.data, fieldPossession.data, fieldTriangles.data, fieldUnits.data]);
  // Worker parses processor polygon JSON and groups exact frames before the
  // data reaches this view. Reduced windows are never treated as exact.
  const tacticalRequest = (artifactId: string | null, columns: readonly string[]) => ({
    artifactId: artifactId ?? "",
    fromNs: Number(tacticalBounds.fromNs),
    toNs: Number(tacticalBounds.toNs),
    maxPoints: TACTICAL_MAX_POINTS,
    columns,
  });
  const teamTactical = useQuery({
    ...tacticalPolygonWindowQuery(
      tacticalRequest(teamArtifact?.artifact_id ?? null, HULL_COLUMNS),
      "group_id",
      "hull_polygon_json",
    ),
    enabled: Boolean(teamArtifact && layers.geometry),
  });
  const territoryTactical = useQuery({
    ...tacticalPolygonWindowQuery(
      tacticalRequest(territoryArtifact?.artifact_id ?? null, TERRITORY_COLUMNS),
      "entity_id",
      "cell_polygon_json",
    ),
    enabled: Boolean(territoryArtifact && layers.territory),
  });
  const influenceTactical = useQuery({
    ...tacticalGridWindowQuery(tacticalRequest(influenceArtifact?.artifact_id ?? null, INFLUENCE_COLUMNS)),
    enabled: Boolean(influenceArtifact && layers.influence),
  });
  const exactPrepared = <T,>(data: { meta: { reduction: unknown }; prepared: T } | undefined) =>
    data?.meta.reduction === null ? data.prepared : null;
  const geometryBuffers = layers.geometry ? exactPrepared<PreparedTacticalPolygonWindow["prepared"]>(teamTactical.data) : null;
  const territoryBuffers = layers.territory ? exactPrepared<PreparedTacticalPolygonWindow["prepared"]>(territoryTactical.data) : null;
  const influenceBuffers = layers.influence ? exactPrepared<PreparedTacticalGridWindow["prepared"]>(influenceTactical.data) : null;
  const reducedOverlay =
    (layers.geometry && teamTactical.data !== undefined && geometryBuffers === null) ||
    (layers.territory && territoryTactical.data !== undefined && territoryBuffers === null) ||
    (layers.influence && influenceTactical.data !== undefined && influenceBuffers === null) ||
    v3Reduced;
  const indexes = useMemo(() => ({
    geometry: geometryBuffers ?? EMPTY_POLYGONS,
    territory: territoryBuffers ?? EMPTY_POLYGONS,
    influence: influenceBuffers ?? EMPTY_GRID,
  }), [geometryBuffers, territoryBuffers, influenceBuffers]);

  const palette = useMemo<PitchPalette>(() => {
    void theme;
    const tokens = readPalette();
    const team = readTeamPalette();
    const colorContext = import.meta.env.MODE === "test"
      ? null
      : document.createElement("canvas").getContext("2d");
    const resolve = (value: string) => {
      const hex = oklchToHex(value);
      if (hex !== null) return hex;
      if (colorContext === null) return value;
      colorContext.fillStyle = value;
      return colorContext.fillStyle;
    };
    return {
      surface: resolve(tokens.surface),
      pitchLine: resolve(tokens.grid),
      home: resolve(team.teamA),
      away: resolve(team.teamB),
      ball: resolve(tokens.text),
      official: resolve(tokens.measurement.PIPELINE_DERIVED ?? tokens.series[2]!),
      extrapolated: resolve(tokens.textMuted),
      selection: resolve(tokens.playhead),
      trail: resolve(tokens.axis),
      label: resolve(tokens.textMuted),
      event: resolve(tokens.measurement.SOURCE_DERIVED ?? tokens.warning),
      halo: resolve(team.halo),
    };
  }, [theme]);

  // Everything the imperative renderer reads lives in refs, so the renderer is
  // created once per mount (and per theme), never per window or per frame.
  const sceneRef = useRef<{
    trackingBuffers: TrackingWindowBuffers;
    indexes: {
      geometry: TacticalPolygonWindowBuffers;
      territory: TacticalPolygonWindowBuffers;
      influence: TacticalGridWindowBuffers;
    };
    teamOrder: readonly string[];
    maxGapNs: number;
    layers: PitchLayers;
    events: readonly PitchEvent[];
    drawnFrameTime: bigint | null | undefined;
    influenceGridTimeNs: bigint | null;
  }>({
    trackingBuffers,
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
    const index = trackingFrameIndexAt(scene.trackingBuffers.frameTimesNs, timeNs, scene.maxGapNs);
    const frameTime = index >= 0 ? scene.trackingBuffers.frameTimesNs[index]! : null;
    const host = hostRef.current;
    if (host) host.dataset.canonicalTimeNs = timeNs === null ? "" : timeNs.toString();
    if (!force && frameTime === scene.drawnFrameTime) return;
    const currentMatchFrame = matchFrameRef.current;
    if (currentMatchFrame) {
      const identity = frameTime === null
        ? null
        : (currentMatchFrame.trackingSource?.artifactId ?? currentMatchFrame.trackingSource?.streamId ?? "tracking") +
          ":" + frameTime;
      const availability = frameTime === null ? "absent" : "available";
      currentMatchFrame.reportResolvedFrame("tracking", {
        identity,
        canonicalTimeNs: frameTime,
        availability,
      });
    }
    scene.drawnFrameTime = frameTime;
    const selected = selectedEntityRef.current;
    renderer.setFrame(scene.trackingBuffers, index, selected, scene.teamOrder);
    const overlay = tacticalOverlayAtBuffers(
      scene.indexes,
      frameTime,
      (groupId) => teamRole(groupId, scene.teamOrder),
      INFLUENCE_MAX_AGE_NS,
    );
    scene.influenceGridTimeNs = overlay.influenceGridTimeNs;
    renderer.setTacticalOverlay(overlay.overlay);
    // Machine-readable evidence of what the canvas shows: the drawn entity
    // frame and the overlay's frame are the same canonical time by construction.
    if (host) {
      host.dataset.drawnFrameNs = frameTime === null ? "" : frameTime.toString();
      host.dataset.sourceFrameNs = frameTime === null ? "" : frameTime.toString();
      host.dataset.overlayHulls = String(overlay.overlay.hulls.length);
      host.dataset.overlayTerritoryCells = String(overlay.overlay.territoryCells.length);
      host.dataset.overlayInfluenceCells = String(overlay.overlay.influenceCells.length);
    }
  }, []);

  useEffect(() => {
    if (selectedEntityRef.current === selectedEntityId) return;
    selectedEntityRef.current = selectedEntityId;
    drawAt(effectiveTimeNs(useAnalysisStore.getState()), true);
  }, [drawAt, selectedEntityId]);

  useEffect(() => {
    if (!pixiParityOracle) return;
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let renderer: PitchRendererHandle | null = null;
    setRendererReady(false);
    void loadPixiPitchRenderer()
      .then(({ createPitchRenderer }) =>
        createPitchRenderer(host, palette, (objectId: string, objectType?: string | null) => onSelectEntity(objectId, objectType)),
      )
      .then((created) => {
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
          trailPointsForTrackingBuffer(
            sceneRef.current.trackingBuffers,
            current.committedRangeNs,
            selectedEntityRef.current,
          ),
          selectedEntityRef.current,
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
  }, [drawAt, onSelectEntity, palette, pixiParityOracle]);

  // New window / tactical data / team order: update the scene and redraw the
  // current frame imperatively.
  useEffect(() => {
    if (!pixiParityOracle) return;
    const scene = sceneRef.current;
    scene.trackingBuffers = trackingBuffers;
    scene.indexes = indexes;
    scene.teamOrder = teamOrder;
    scene.maxGapNs = maxGapNs;
    drawAt(effectiveTimeNs(useAnalysisStore.getState()), true);
    setInfluenceGridTimeNs(scene.influenceGridTimeNs);
  }, [drawAt, indexes, maxGapNs, pixiParityOracle, teamOrder, trackingBuffers]);

  // Per-frame path: a store subscription, never a React render.
  useEffect(() => {
    return useAnalysisStore.subscribe((state, previous) => {
      const next = effectiveTimeNs(state);
      if (next !== effectiveTimeNs(previous)) drawAt(next);
    });
  }, [drawAt]);

  useEffect(() => {
    rendererRef.current?.setTrail(
      trailPointsForTrackingBuffer(trackingBuffers, committedRangeNs, selectedEntityId),
      selectedEntityId,
    );
  }, [committedRangeNs, selectedEntityId, trackingBuffers]);

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
  useEffect(() => {
    rendererRef.current?.setEntityLabels?.(entityLabels);
  }, [entityLabels, rendererReady]);

  const [, bumpHeader] = useReducer((value: number) => value + 1, 0);
  useEffect(() => {
    let lastEmit = 0;
    return useAnalysisStore.subscribe((state, previous) => {
      const next = effectiveTimeNs(state);
      if (next === effectiveTimeNs(previous)) return;
      // The DOM summary is a low-frequency text alternative, not a per-frame
      // render: it updates at most five times per second during playback.
      const now = performance.now();
      if (now - lastEmit < 200) return;
      lastEmit = now;
      if (pixiParityOracle) setInfluenceGridTimeNs(sceneRef.current.influenceGridTimeNs);
      bumpHeader();
    });
  }, [pixiParityOracle]);

  const currentTimeNs = v3TimeNs;
  const currentFrameIndex = trackingFrameIndexAt(trackingBuffers.frameTimesNs, currentTimeNs, maxGapNs);
  const summary = trackingFrameSummaryAt(trackingBuffers, currentFrameIndex);
  const selectedEntity = trackingEntityAt(trackingBuffers, currentFrameIndex, selectedEntityId);
  const teamLabel = (groupId: string | null) =>
    groupId === null ? null : (teamLabels.get(groupId) ?? groupId);
  const tacticalLoading =
    (layers.geometry && teamTactical.isFetching) ||
    (layers.territory && territoryTactical.isFetching) ||
    (layers.influence && influenceTactical.isFetching) ||
    fieldUnits.isFetching || fieldPossession.isFetching ||
    (tacticalRelationMode === "stable-graph" && fieldEdges.isFetching) ||
    (tacticalRelationMode === "selected-triangles" && fieldTriangles.isFetching) ||
    (tacticalRelationMode === "attacker-defender" && fieldInteractions.isFetching);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="relative z-20 shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-2">
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
                label="Occupied area"
                title="Optional Level A convex-hull occupied-area summary per team at the current frame"
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
                title="Level C arrival-time influence grid (MODEL_ESTIMATED, sampled ≤ 1 Hz, fixed 0–5 s color domain; color saturates only)"
                pressed={layers.influence}
                onToggle={() => setLayers((current) => ({ ...current, influence: !current.influence }))}
              />
            ) : null}
            <button
              type="button"
              aria-pressed={cameraMode === "tactical-map"}
              onClick={() => { setCameraMode("tactical-map"); fieldSceneRef.current?.setCameraMode("tactical-map"); }}
              className={cameraMode === "tactical-map" ? "t-control-compact rounded-control border border-accent/60 bg-accent/10 px-2 text-[11px] text-text-primary" : "t-control-compact rounded-control border border-border-subtle px-2 text-[11px] text-text-muted hover:border-border-strong hover:text-text-secondary"}
            >Tactical Map</button>
            <button type="button" aria-pressed={cameraMode === "structure-lift"} onClick={() => { setCameraMode("structure-lift"); fieldSceneRef.current?.setCameraMode("structure-lift"); }} className={cameraMode === "structure-lift" ? "t-control-compact rounded-control border border-accent/60 bg-accent/10 px-2 text-[11px] text-text-primary" : "t-control-compact rounded-control border border-border-subtle px-2 text-[11px] text-text-muted hover:border-border-strong hover:text-text-secondary"}>Structure Lift</button>
            <button type="button" aria-pressed={cameraMode === "perspective"} onClick={() => { setCameraMode("perspective"); fieldSceneRef.current?.setCameraMode("perspective"); }} className={cameraMode === "perspective" ? "t-control-compact rounded-control border border-accent/60 bg-accent/10 px-2 text-[11px] text-text-primary" : "t-control-compact rounded-control border border-border-subtle px-2 text-[11px] text-text-muted hover:border-border-strong hover:text-text-secondary"}>Perspective Explore</button>
            <button type="button" onClick={() => fieldSceneRef.current?.focusSelected()} disabled={!selectedEntity || selectedEntity.isBall} className="t-control-compact rounded-control border border-border-subtle px-2 text-[11px] text-text-muted disabled:opacity-40 hover:border-border-strong hover:text-text-secondary">Focus selected</button>
            <button
              type="button"
              onClick={() => {
                if (pixiParityOracle) rendererRef.current?.resetView();
                else fieldSceneRef.current?.resetView();
              }}
              title="Reset the active camera preset"
              className="t-control-compact rounded-control border border-border-subtle px-2 text-[11px] text-text-muted transition-colors duration-quick hover:border-border-strong hover:text-text-secondary"
            >Reset camera</button>
          </div>
        </div>
      </header>
      <div className="relative min-h-0 flex-1">
        <div
          ref={hostRef}
          role="region"
          aria-label={
            summary === null
              ? `Pitch replay for ${stream.stream_id}: no tracking frame at ${currentTimeNs === null ? "the current time" : formatClockNs(currentTimeNs)}`
              : `Pitch replay for ${stream.stream_id} at ${formatClockNs(BigInt(summary.tRelNs))}: ${summary.players} players, ball ${summary.ballDetected === false ? "extrapolated" : "tracked"}`
          }
          data-testid="pitch-canvas"
          data-renderer={pixiParityOracle ? "pixi" : "r3f"}
          data-renderer-ready={rendererReady ? "true" : "false"}
          data-frame-ns={summary === null ? "" : String(summary.tRelNs)}
          data-pitch-length-m={stream.pitch_dimensions_m?.length_m ?? ""}
          data-pitch-width-m={stream.pitch_dimensions_m?.width_m ?? ""}
          className="relative h-full w-full"
        >
          {pixiParityOracle ? null : (
            <FieldSceneView
              ref={fieldSceneRef}
              hostRef={hostRef}
              matchFrame={matchFrame!}
              trackingBuffers={trackingBuffers}
              geometryBuffers={indexes.geometry}
              territoryBuffers={indexes.territory}
              influenceBuffers={indexes.influence}
              tacticalV3Index={tacticalV3Index}
              tacticalRelationMode={tacticalRelationMode}
              scalarFieldMode={scalarFieldMode}
              trackingMaxAgeNs={maxGapNs}
              influenceMaxAgeNs={INFLUENCE_MAX_AGE_NS}
              teamOrder={teamOrder}
              teamLabels={teamLabels}
              entityLabels={entityLabels}
              trackingPalette={{
                home: palette.home,
                away: palette.away,
                other: palette.extrapolated,
                ball: palette.ball,
              }}
              tacticalPalette={{
                home: palette.home,
                away: palette.away,
                other: palette.extrapolated,
                event: palette.event,
                selection: palette.selection,
              }}
              events={events}
              layers={layers}
              onReady={handleSceneReady}
              onInfluenceGridTime={handleInfluenceGridTime}
              cameraMode={cameraMode}
              onCameraModeChange={setCameraMode}
            />
          )}
          {!pixiParityOracle ? (
            <div className="pointer-events-none absolute left-2 top-2 rounded bg-black/70 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-white">
              Source native
            </div>
          ) : null}
        </div>
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
          {summary === null ? "—" : formatClockNs(BigInt(summary.tRelNs))} · {cameraMode === "tactical-map"
            ? "Tactical Map · pan/zoom · rotation locked"
            : cameraMode === "structure-lift"
              ? "Structure Lift · orbit/pan/zoom"
              : "Perspective Explore · orbit/pan/zoom"}
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
        {teamArtifact && layers.geometry ? <span>Occupied area: optional convex hull, current frame</span> : null}
        {territoryArtifact && layers.territory ? <span>Territory: clipped Voronoi, current frame</span> : null}
        {influenceArtifact && layers.influence ? (
          <span>
            Influence: MODEL_ESTIMATED · fixed color domain 0–5 s
          {influenceGridTimeNs !== null ? ` · grid @ ${formatClockNs(influenceGridTimeNs)}` : " · no grid within 1.5 s"}
          </span>
        ) : null}
        <span>Trails: committed range</span>
        <span>Tracking: source-planar X/Y</span>
        <span className="mono ml-auto tabular">
          frame {currentFrameIndex >= 0 ? currentFrameIndex + 1 : "—"} / {trackingBuffers.frameTimesNs.length}
        </span>
      </footer>
    </div>
  );
}
