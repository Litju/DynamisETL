import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useMemo, useState } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import {
  CAMERA_PRESETS,
  extractFrames,
  frameIndexAt,
  landmarksAt,
  NO_OVERLAYS,
  overlaysFromParameters,
  summarizeFrame,
  type CameraPreset,
  type PoseLandmark,
} from "@/components/pose/pose-model";
import type { StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { artifactQuery, methodologyQuery, metricsQuery, sessionQuery, windowQuery } from "@/lib/api/queries";
import { formatMetricValue } from "@/lib/measurement";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatClockNs, NS_PER_SECOND } from "@/lib/time";

const PoseCanvas = lazy(() => import("@/components/pose/PoseScene"));

const MAX_POSE_POINTS = 20_000;
const DEFAULT_WINDOW_NS = 10n * NS_PER_SECOND;

/**
 * 3D biomechanics laboratory: source landmarks in a local analytical frame.
 * No realistic body mesh, no anatomical parent tree; processor segments/angles
 * are rendered only when the versioned processor parameters declare them, and
 * the frame label always states that Z is player-centroid-relative.
 */
export function PoseViewer() {
  const context = useAnalysisContext();
  const datasetId = context?.datasetId ?? null;
  const sessionId = context?.sessionId ?? null;
  const streamId = context?.streamId ?? null;
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const playheadNs = useAnalysisStore((state) => state.playheadNs);
  const playing = useAnalysisStore((state) => state.playing);
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  const hoveredJoint = useAnalysisStore((state) => state.hoveredJoint);

  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const stream: StreamView | null = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === streamId) ?? null;
  }, [session.data, streamId]);

  const effective = playheadNs ?? committedTimeNs;
  const windowBounds = useMemo(() => {
    if (context?.fromNs != null && context.toNs != null) {
      return { fromNs: Number(context.fromNs), toNs: Number(context.toNs) };
    }
    if (effective !== null) {
      return { fromNs: Number(effective - DEFAULT_WINDOW_NS), toNs: Number(effective + DEFAULT_WINDOW_NS) };
    }
    return null;
  }, [context?.fromNs, context?.toNs, effective]);

  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({ ...artifactQuery(artifactId ?? ""), enabled: Boolean(artifactId) });
  const window = useQuery({
    ...windowQuery({
      artifactId: artifactId ?? "",
      ...(windowBounds ? { fromNs: windowBounds.fromNs, toNs: windowBounds.toNs } : {}),
      columns: [
        "t_rel_ns",
        "subject_id",
        "joint_name",
        "is_available",
        "x_m",
        "y_m",
        "z_m",
        "error_m",
      ],
      maxPoints: MAX_POSE_POINTS,
    }),
    enabled: Boolean(artifactId),
  });
  const metrics = useQuery({
    ...metricsQuery({ streamId: streamId ?? undefined, limit: 50 }),
    enabled: Boolean(streamId),
  });
  const processorAlgorithmId = useMemo(() => {
    const rows = metrics.data?.rows ?? [];
    const poseMetric = rows.find((row) => (row.algorithm_id ?? "").startsWith("pose."));
    return poseMetric?.algorithm_id ?? null;
  }, [metrics.data]);
  const methodology = useQuery({
    ...methodologyQuery(processorAlgorithmId ?? ""),
    enabled: Boolean(processorAlgorithmId),
  });

  const frames = useMemo(
    () =>
      extractFrames(
        (window.data?.rows ?? []) as Array<{
          t_rel_ns?: unknown;
          subject_id?: unknown;
          joint_name?: unknown;
          is_available?: unknown;
          x_m?: unknown;
          y_m?: unknown;
          z_m?: unknown;
          error_m?: unknown;
        }>,
      ),
    [window.data],
  );
  const overlays = useMemo(
    () =>
      methodology.data?.algorithm
        ? overlaysFromParameters(methodology.data.algorithm.parameters)
        : NO_OVERLAYS,
    [methodology.data],
  );

  const [preset, setPreset] = useState<CameraPreset>("reset");
  const [showErrorRadii, setShowErrorRadii] = useState(false);

  if (!context) return <StatePanel state="empty" title="Open a laboratory session first." />;
  if (session.isPending) return <LoadingPanel label="Loading session streams" />;
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }
  if (streamId === null) {
    return (
      <StatePanel
        state="empty"
        title="No stream selected."
        detail="Select a pose stream in the explorer to open the landmark viewer."
      />
    );
  }
  if (stream === null) {
    return (
      <StatePanel state="unavailable" title="Stream is not part of this session." />
    );
  }
  if (stream.modality !== "pose") {
    return (
      <StatePanel
        state="unavailable"
        title="This stream is not a pose stream."
        detail={`The 3D laboratory renders pose landmarks only; ${stream.stream_id} is ${stream.modality}.`}
      />
    );
  }
  if (artifactId === null) {
    return (
      <StatePanel
        state="unavailable"
        title="No canonical pose artifact is registered."
        detail="Run the deterministic ingest path before viewing landmarks."
      />
    );
  }
  if (artifact.isError || window.isError) {
    const error = artifact.error ?? window.error;
    if (error instanceof ApiError && error.state === "dense_window_too_large") {
      return (
        <StatePanel
          state="blocked"
          title="Pose window too large."
          detail="Narrow the range in the transport; the viewer never downsamples landmark frames."
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
  if (artifact.isPending || window.isPending) return <LoadingPanel label="Loading pose window" />;
  if (window.data.meta.reduction !== null) {
    return (
      <StatePanel
        state="blocked"
        title="This window is display-reduced."
        detail="Landmark viewing requires exact frames; narrow from_ns/to_ns so the window fits the point budget."
      />
    );
  }
  if (frames.length === 0 || frames.every((frame) => !frame.observed)) {
    return (
      <StatePanel
        state="unavailable"
        title="No observed landmark is available in this window."
        detail="Unavailable joints are never imputed or replaced."
      />
    );
  }

  const currentTime = playheadNs ?? committedTimeNs;
  const currentLandmarks = landmarksAt(frames, currentTime);
  const currentFrameIndex = currentTime === null ? 0 : frameIndexAt(frames, currentTime);
  const summary = summarizeFrame(
    currentFrameIndex >= 0 ? (frames[currentFrameIndex] ?? null) : null,
  );
  const inspected = [...currentLandmarks].find(
    (landmark: PoseLandmark) => landmark.jointName === (selectedJoint ?? hoveredJoint),
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex min-h-9 shrink-0 flex-wrap items-center gap-3 border-b border-border-subtle bg-surface-1 px-3 py-1 text-[11px] text-text-muted">
        <ModalityBadge modality={stream.modality} />
        <span className="mono">{stream.stream_id}</span>
        <MeasurementClassBadge measurementClass={stream.measurement_class} compact />
        <span className="mono">skeleton {stream.skeleton_id ?? "unregistered"}</span>
        <span className="text-quality-warning">
          local analytical frame · Z is player-centroid-relative, not absolute height
        </span>
        <span className="tabular">
          {summary.observedLandmarks} observed · {summary.unavailableLandmarks} unavailable
        </span>
        {summary.meanErrorM !== null ? (
          <span className="tabular">
            mean provider p90 predicted error radius{" "}
            {formatMetricValue(summary.meanErrorM, "m").text}
          </span>
        ) : null}
      </header>
      <div className="flex min-h-0 flex-1">
        <div className="relative min-h-0 flex-1" data-testid="pose-canvas">
          <Suspense fallback={<LoadingPanel label="Loading 3D renderer" />}>
            <PoseCanvas
              frames={frames}
              overlays={overlays}
              preset={preset}
              playing={playing}
              showErrorRadii={showErrorRadii}
            />
          </Suspense>
        </div>
        <aside className="w-60 shrink-0 overflow-y-auto border-l border-border-subtle bg-surface-1 p-2 text-[11px]">
          <div className="mb-2">
            <span className="text-[10px] uppercase tracking-wider text-text-muted">camera</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {CAMERA_PRESETS.map((candidate) => (
                <button
                  key={candidate}
                  type="button"
                  aria-pressed={preset === candidate}
                  onClick={() => setPreset(candidate)}
                  className={
                    preset === candidate
                      ? "rounded-control bg-surface-3 px-1.5 py-0.5 text-text-primary"
                      : "rounded-control border border-border-subtle px-1.5 py-0.5 text-text-muted hover:text-text-secondary"
                  }
                >
                  {candidate.replace("_", "-")}
                </button>
              ))}
            </div>
          </div>
          <label className="mb-2 flex items-center gap-1 text-text-muted">
            <input
              type="checkbox"
              checked={showErrorRadii}
              onChange={(event) => setShowErrorRadii(event.target.checked)}
            />
            provider p90 predicted error radius
          </label>
          <div className="mb-2">
            <span className="text-[10px] uppercase tracking-wider text-text-muted">
              processor overlays
            </span>
            <p className="text-text-muted">
              {overlays.source === "none"
                ? "none declared for this stream's processor revision"
                : `${overlays.segments.length} segment(s), ${overlays.angles.length} angle(s) from processor parameters`}
            </p>
          </div>
          <div className="mb-2">
            <span className="text-[10px] uppercase tracking-wider text-text-muted">
              observed landmarks
            </span>
            <ul className="mt-1 flex flex-wrap gap-1" aria-label="Observed landmarks">
              {currentLandmarks.map((landmark) => (
                <li key={landmark.jointName}>
                  <button
                    type="button"
                    aria-pressed={selectedJoint === landmark.jointName}
                    onClick={() => useAnalysisStore.getState().selectJoint(landmark.jointName)}
                    className={
                      selectedJoint === landmark.jointName
                        ? "mono rounded-control bg-surface-3 px-1.5 py-0.5 text-text-primary"
                        : "mono rounded-control border border-border-subtle px-1.5 py-0.5 text-text-muted hover:text-text-secondary"
                    }
                  >
                    {landmark.jointName}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div className="mb-2">
            <span className="text-[10px] uppercase tracking-wider text-text-muted">
              frame time
            </span>
            <p className="mono text-text-secondary">
              {currentTime !== null ? `${formatClockNs(currentTime)}` : "playhead unavailable"}
            </p>
          </div>
          {inspected ? (
            <div>
              <span className="text-[10px] uppercase tracking-wider text-text-muted">
                selected landmark
              </span>
              <p className="mono text-text-secondary">{inspected.jointName}</p>
              <p className="mono text-text-muted">
                x {inspected.xM.toFixed(3)} · y {inspected.yM.toFixed(3)} · z{" "}
                {inspected.zM.toFixed(3)} m
              </p>
              <p className="text-text-muted">
                {inspected.errorM !== null
                  ? `provider p90 predicted error radius ${formatMetricValue(inspected.errorM, "m").text}`
                  : "no provider error radius for this landmark"}
              </p>
            </div>
          ) : (
            <p className="text-text-muted">
              Select a landmark in the viewer to inspect its coordinates and provider error radius.
              Source landmarks carry no invented anatomical parentage.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

export default PoseViewer;
