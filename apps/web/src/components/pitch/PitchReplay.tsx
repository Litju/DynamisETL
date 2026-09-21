import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import {
  assignGroups,
  buildFrames,
  entitiesAt,
  frameIndexAt,
  isTrackingStream,
  summarizeFrame,
  trailForRange,
} from "@/components/pitch/pitch-model";
import {
  createPitchRenderer,
  DEFAULT_PITCH_LAYERS,
  type PitchEvent,
  type PitchLayers,
  type PitchPalette,
  type PitchRendererHandle,
} from "@/components/pitch/pitch-renderer";
import { eventStreams } from "@/lib/capabilities";
import type { StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { artifactQuery, sessionQuery, windowQuery } from "@/lib/api/queries";
import { readPalette } from "@/lib/chart-palette";
import { windowAround } from "@/lib/dense-window";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatClockNs, formatDurationNs } from "@/lib/time";

const MAX_REPLAY_POINTS = 20_000;
const MAX_EVENT_POINTS = 2_000;

/** Shape served event rows into renderer marks, dropping unplaceable ones. */
export function toPitchEvents(rows: ReadonlyArray<Record<string, unknown>>): PitchEvent[] {
  const events: PitchEvent[] = [];
  for (const row of rows) {
    const x = row["x_m"];
    const y = row["y_m"];
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
 * Field laboratory: PixiJS pitch replay over canonical tracking windows.
 * React owns the scene lifecycle and selection; the renderer owns frame-rate
 * updates (playhead subscription), so playback never triggers reconciliation.
 */
export function PitchReplay() {
  const context = useAnalysisContext();
  const datasetId = context?.datasetId ?? null;
  const sessionId = context?.sessionId ?? null;
  const streamId = context?.streamId ?? null;

  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const stream: StreamView | null = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === streamId) ?? null;
  }, [session.data, streamId]);

  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const playheadNs = useAnalysisStore((state) => state.playheadNs);
  const effective = playheadNs ?? committedTimeNs;
  const fromNs = context?.fromNs ?? null;
  const toNs = context?.toNs ?? null;

  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({
    ...artifactQuery(artifactId ?? ""),
    enabled: Boolean(artifactId),
  });

  // Replay needs exact entity frames, so the window is sized from the
  // artifact's own measured density rather than a fixed duration that happens
  // to suit one source: SkillCorner runs 182 rows/s and DFL 575 rows/s over
  // the same nominal match.
  const windowBounds = useMemo(
    () =>
      windowAround(artifact.data, {
        anchorNs: effective,
        explicit: fromNs !== null && toNs !== null ? { fromNs, toNs } : null,
        maxPoints: MAX_REPLAY_POINTS,
      }),
    [artifact.data, effective, fromNs, toNs],
  );
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
      ...(windowBounds
        ? { fromNs: Number(windowBounds.fromNs), toNs: Number(windowBounds.toNs) }
        : {}),
      columns: ["t_rel_ns", "event_id", "event_type", "event_subtype", "x_m", "y_m"],
      maxPoints: MAX_EVENT_POINTS,
    }),
    enabled: Boolean(eventArtifactId) && windowBounds !== null,
  });
  const events = useMemo(
    () => toPitchEvents(eventWindow.data?.rows ?? []),
    [eventWindow.data],
  );

  const handleSelectEntity = useCallback(
    (objectId: string) => {
      useAnalysisStore.getState().selectEntity(objectId);
      context?.selectSubject(objectId);
    },
    [context],
  );
  const window = useQuery({
    ...windowQuery({
      artifactId: artifactId ?? "",
      ...(windowBounds
        ? { fromNs: Number(windowBounds.fromNs), toNs: Number(windowBounds.toNs) }
        : {}),
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
    // The bounds come from the artifact, so the window waits for it rather
    // than firing an unbounded request for the whole recording first.
    enabled: Boolean(artifactId) && windowBounds !== null,
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
  if (artifact.isPending || windowBounds === null || window.isPending) {
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
      events={events}
      explicitRange={windowBounds.explicit}
      windowLabel={`${formatDurationNs(windowBounds.toNs - windowBounds.fromNs)} window`}
      onSelectEntity={handleSelectEntity}
    />
  );
}

/** A scene layer switch: pressed state carries text and border, not colour alone. */
function LayerToggle({
  label,
  pressed,
  onToggle,
}: {
  label: string;
  pressed: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onToggle}
      className={
        pressed
          ? "rounded-control border border-accent bg-surface-3 px-2 py-0.5 text-[11px] text-text-primary"
          : "rounded-control border border-border-subtle px-2 py-0.5 text-[11px] text-text-muted transition-colors duration-quick hover:border-border-strong hover:text-text-secondary"
      }
    >
      {label}
    </button>
  );
}

function PitchView({
  stream,
  rows,
  events,
  explicitRange,
  windowLabel,
  onSelectEntity,
}: {
  stream: StreamView;
  rows: Array<Record<string, unknown>>;
  events: readonly PitchEvent[];
  explicitRange: boolean;
  windowLabel: string;
  onSelectEntity: (objectId: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<PitchRendererHandle | null>(null);
  const selectedEntityId = useAnalysisStore((state) => state.selectedEntityId);
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);
  // The scene is rebuilt when the window changes; these refs carry the current
  // presentation state into the newly created renderer.
  const layersRef = useRef<PitchLayers>(DEFAULT_PITCH_LAYERS);
  const eventsRef = useRef<readonly PitchEvent[]>(events);
  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

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
  const groups = useMemo(() => assignGroups(frames), [frames]);

  const palette = useMemo<PitchPalette>(() => {
    const tokens = readPalette();
    return {
      surface: tokens.surface,
      pitchLine: tokens.grid,
      home: tokens.measurement.RAW_MEASURED ?? tokens.series[0]!,
      away: tokens.measurement.SOURCE_DERIVED ?? tokens.series[1]!,
      ball: tokens.text,
      official: tokens.measurement.PIPELINE_DERIVED ?? tokens.series[2]!,
      extrapolated: tokens.textMuted,
      selection: tokens.playhead,
      trail: tokens.axis,
      label: tokens.textMuted,
      event: tokens.measurement.SOURCE_DERIVED ?? tokens.warning,
    };
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let renderer: PitchRendererHandle | null = null;
    void createPitchRenderer(host, palette, (objectId) => {
      useAnalysisStore.getState().selectEntity(objectId);
      onSelectEntity(objectId);
    }).then((created) => {
      if (disposed) {
        created.destroy();
        return;
      }
      renderer = created;
      rendererRef.current = created;
      created.setLayers(layersRef.current);
      created.setEvents(eventsRef.current);
      created.setFrame(
        entitiesAt(frames, useAnalysisStore.getState().playheadNs),
        groups,
        useAnalysisStore.getState().selectedEntityId,
      );
    });
    return () => {
      disposed = true;
      renderer?.destroy();
      rendererRef.current = null;
    };
    // The scene is rebuilt only when the loaded tracking window changes.
  }, [frames, groups, palette, onSelectEntity]);

  useEffect(() => {
    return useAnalysisStore.subscribe((state, previous) => {
      const renderer = rendererRef.current;
      if (!renderer) return;
      const next = state.playheadNs ?? state.committedTimeNs;
      const before = previous.playheadNs ?? previous.committedTimeNs;
      if (next !== before) {
        renderer.setFrame(entitiesAt(frames, next), groups, state.selectedEntityId);
      }
      if (state.selectedEntityId !== previous.selectedEntityId) {
        renderer.setFrame(entitiesAt(frames, next), groups, state.selectedEntityId);
      }
    });
  }, [frames, groups]);

  useEffect(() => {
    const renderer = rendererRef.current;
    if (!renderer) return;
    renderer.setTrail(
      trailForRange(frames, committedRangeNs, selectedEntityId),
      groups,
      selectedEntityId,
    );
  }, [committedRangeNs, frames, groups, selectedEntityId]);

  // Layer visibility is renderer-local presentation state: it changes nothing
  // about the data and never belongs in the durable URL.
  const [layers, setLayers] = useState<PitchLayers>(DEFAULT_PITCH_LAYERS);
  useEffect(() => {
    layersRef.current = layers;
    rendererRef.current?.setLayers(layers);
  }, [layers]);
  useEffect(() => {
    rendererRef.current?.setEvents(events);
  }, [events]);

  const [, bumpHeader] = useReducer((value: number) => value + 1, 0);
  useEffect(() => {
    let lastEmit = 0;
    return useAnalysisStore.subscribe((state, previous) => {
      const next = state.playheadNs ?? state.committedTimeNs;
      const before = previous.playheadNs ?? previous.committedTimeNs;
      if (next === before && state.selectedEntityId === previous.selectedEntityId) return;
      // The DOM summary is a low-frequency text alternative, not a per-frame
      // render: it updates at most five times per second during playback.
      const now = performance.now();
      if (now - lastEmit < 200) return;
      lastEmit = now;
      bumpHeader();
    });
  }, []);

  const currentTimeNs =
    useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
  const currentFrameIndex = frameIndexAt(frames, currentTimeNs ?? 0n);
  const summary = summarizeFrame(currentFrameIndex >= 0 ? frames[currentFrameIndex]! : null);
  const selectedFrame = entitiesAt(frames, currentTimeNs);
  const selectedEntity =
    selectedEntityId === null
      ? null
      : (selectedFrame.find((entity) => entity.objectId === selectedEntityId) ?? null);

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
          </div>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted">
          <span className="tabular">
            {summary === null
              ? "No frame at this time"
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
          <div role="group" aria-label="Scene layers" className="ml-auto flex items-center gap-1">
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
            <button
              type="button"
              onClick={() => rendererRef.current?.resetView()}
              title="Frame the whole pitch again"
              className="rounded-control border border-border-subtle px-2 py-0.5 text-[11px] text-text-muted transition-colors duration-quick hover:border-border-strong hover:text-text-secondary"
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
          aria-label={`Pitch replay for ${stream.stream_id}`}
          data-testid="pitch-canvas"
          className="h-full w-full"
        />
        <div className="pointer-events-none absolute left-2 top-2 max-w-64 rounded-control border border-border-subtle bg-surface-1/90 px-2 py-1 text-[11px]">
          {selectedEntity ? (
            <>
              <div className="mono text-text-secondary">
                {selectedEntity.objectId} · {selectedEntity.objectType}
              </div>
              <div className="mono text-text-muted">
                x {selectedEntity.xM.toFixed(2)} m · y {selectedEntity.yM.toFixed(2)} m
              </div>
              <div className="text-text-muted">
                {selectedEntity.detected === false ? "extrapolated" : "detected"}
                {selectedEntity.groupId ? ` · group ${selectedEntity.groupId}` : ""}
              </div>
            </>
          ) : (
            <span className="text-text-muted">
              Select a player or the ball on the pitch; entities are never fused across groups.
            </span>
          )}
        </div>
        <div className="pointer-events-none absolute bottom-2 left-2 rounded-control border border-border-subtle bg-surface-1/90 px-2 py-1 text-[10px] text-text-muted">
          {summary === null ? "—" : formatClockNs(BigInt(summary.tRelNs))} · wheel zoom, drag pan;
          hollow = extrapolated
        </div>
        {selectedEntityId !== null ? (
          <button
            type="button"
            onClick={() => {
              useAnalysisStore.getState().selectEntity(null);
            }}
            className="absolute bottom-2 right-2 rounded-control border border-border-subtle bg-surface-1/90 px-2 py-1 text-[10px] text-text-muted hover:border-border-strong"
            title="Clear the current selection"
          >
            clear selection: <span className="mono">{selectedEntityId}</span>
          </button>
        ) : null}
      </div>
      <footer className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-border-subtle bg-surface-1 px-4 py-1.5 text-[10px] text-text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block size-2 rounded-full"
            style={{ backgroundColor: "var(--d-measurement-raw)" }}
          />
          Detected
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block size-2 rounded-full border"
            style={{ borderColor: "var(--d-text-muted)" }}
          />
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
        <span>Trails cover the committed range only</span>
        <span>Possession and context flags appear only when the source provides them</span>
        <span className="mono ml-auto tabular">frame {currentFrameIndex}</span>
      </footer>
    </div>
  );
}
