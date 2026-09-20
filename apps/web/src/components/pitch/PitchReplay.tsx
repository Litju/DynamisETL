import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

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
  type PitchPalette,
  type PitchRendererHandle,
} from "@/components/pitch/pitch-renderer";
import type { StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { artifactQuery, sessionQuery, windowQuery } from "@/lib/api/queries";
import { readPalette } from "@/lib/chart-palette";
import { windowAround } from "@/lib/dense-window";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatClockNs, formatDurationNs } from "@/lib/time";

const MAX_REPLAY_POINTS = 20_000;

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
      explicitRange={windowBounds.explicit}
      windowLabel={`${formatDurationNs(windowBounds.toNs - windowBounds.fromNs)} window`}
      onSelectEntity={handleSelectEntity}
    />
  );
}

function PitchView({
  stream,
  rows,
  explicitRange,
  windowLabel,
  onSelectEntity,
}: {
  stream: StreamView;
  rows: Array<Record<string, unknown>>;
  explicitRange: boolean;
  windowLabel: string;
  onSelectEntity: (objectId: string) => void;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<PitchRendererHandle | null>(null);
  const selectedEntityId = useAnalysisStore((state) => state.selectedEntityId);
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);

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
      <header className="flex min-h-9 shrink-0 flex-wrap items-center gap-3 border-b border-border-subtle bg-surface-1 px-3 py-1 text-[11px] text-text-muted">
        <ModalityBadge modality={stream.modality} />
        <span className="mono">{stream.stream_id}</span>
        <MeasurementClassBadge measurementClass={stream.measurement_class} compact />
        <span className="mono">sync {stream.synchronization_spec_id}</span>
        <span className="tabular">
          {summary === null
            ? "no frame at this time"
            : `${summary.players} players · ${summary.extrapolated} extrapolated`}
        </span>
        <span className="tabular">
          {summary === null
            ? "—"
            : `ball ${summary.ballDetected === null ? "detection unknown" : summary.ballDetected ? "detected" : "extrapolated"}`}
        </span>
        <span>{explicitRange ? "selected range" : windowLabel}</span>
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
      <footer className="flex h-7 shrink-0 items-center gap-3 border-t border-border-subtle px-3 text-[10px] text-text-muted">
        <span>detected ≠ extrapolated; trails cover the committed range only</span>
        <span>possession and context flags appear only when the source provides them</span>
        <span className="mono">frame index {currentFrameIndex}</span>
      </footer>
    </div>
  );
}
