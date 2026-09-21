import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

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
  type DisplayConnectionDefinition,
  type PoseLandmark,
} from "@/components/pose/pose-model";
import type { StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { artifactQuery, methodologyQuery, metricsQuery, sessionQuery, windowQuery } from "@/lib/api/queries";
import { usePoseSubjects } from "@/components/pose/use-pose-subjects";
import { windowAround } from "@/lib/dense-window";
import { formatMetricValue } from "@/lib/measurement";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatClockNs } from "@/lib/time";

const PoseCanvas = lazy(() => import("@/components/pose/PoseScene"));

const MAX_POSE_POINTS = 20_000;

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
  const [rendererReady, setRendererReady] = useState(false);

  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const stream: StreamView | null = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === streamId) ?? null;
  }, [session.data, streamId]);

  const effective = playheadNs ?? committedTimeNs;
  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({ ...artifactQuery(artifactId ?? ""), enabled: Boolean(artifactId) });

  // A pose artifact interleaves every observed subject on one time axis: the
  // SkillCorner period holds 21.4M rows across 23 subjects. Landmark viewing
  // needs exact frames, so the window is both scoped to one subject and sized
  // from the artifact's measured per-subject density.
  //
  // A pose stream that declares no subject of its own resolves identities from
  // the stable artifact/session authority; the current playhead never changes
  // the selected individual.
  const observed = usePoseSubjects(
    artifact.data,
    session.data?.participants ?? [],
    stream?.subject_id ?? null,
  );
  const observedSubjectList = observed.subjects;
  const selectedSubject = context?.subjectId ?? null;
  const streamSubject = stream?.subject_id ?? null;
  const subjectId = useMemo(() => {
    if (selectedSubject !== null) return selectedSubject;
    return observedSubjectList[0] ?? streamSubject;
  }, [observedSubjectList, selectedSubject, streamSubject]);

  const explicitFromNs = context?.fromNs ?? null;
  const explicitToNs = context?.toNs ?? null;
  const artifactData = artifact.data;
  const windowBounds = useMemo(
    () =>
      windowAround(artifactData, {
        anchorNs: effective,
        explicit:
          explicitFromNs !== null && explicitToNs !== null
            ? { fromNs: explicitFromNs, toNs: explicitToNs }
            : null,
        maxPoints: MAX_POSE_POINTS,
        entityScoped: subjectId !== null,
      }),
    [artifactData, effective, explicitFromNs, explicitToNs, subjectId],
  );

  const window = useQuery({
    ...windowQuery({
      artifactId: artifactId ?? "",
      ...(windowBounds
        ? { fromNs: Number(windowBounds.fromNs), toNs: Number(windowBounds.toNs) }
        : {}),
      ...(subjectId !== null ? { entityId: subjectId } : {}),
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
    enabled: Boolean(artifactId) && windowBounds !== null,
  });
  const metrics = useQuery({
    ...metricsQuery({
      streamId: streamId ?? undefined,
      ...(subjectId !== null ? { subjectId } : {}),
      limit: 50,
    }),
    enabled: Boolean(streamId),
  });
  // Analytical overlays come from the processor revision that produced this
  // stream's metrics, and the methodology endpoint is keyed by metric id: an
  // algorithm id resolves to nothing there, which silently emptied every
  // overlay. The first pose metric of the stream names the revision to read.
  const poseMetricId = useMemo(() => {
    const rows = metrics.data?.rows ?? [];
    const poseMetric = rows.find((row) => (row.algorithm_id ?? "").startsWith("pose."));
    return poseMetric?.metric_id ?? null;
  }, [metrics.data]);
  const methodology = useQuery({
    ...methodologyQuery(poseMetricId ?? ""),
    enabled: Boolean(poseMetricId),
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
        subjectId,
      ),
    [subjectId, window.data],
  );
  const overlays = useMemo(
    () =>
      methodology.data?.algorithm
        ? overlaysFromParameters(methodology.data.algorithm.parameters)
        : NO_OVERLAYS,
    [methodology.data],
  );

  const [preset, setPreset] = useState<CameraPreset>("reset");
  const [showProviderSkeleton, setShowProviderSkeleton] = useState(true);
  const [showTorsoCue, setShowTorsoCue] = useState(true);
  const [showFootContact, setShowFootContact] = useState(true);
  const [showHandContact, setShowHandContact] = useState(true);
  const [showHeadNeck, setShowHeadNeck] = useState(true);
  const [showArticulationAngles, setShowArticulationAngles] = useState(true);
  const [showSegments, setShowSegments] = useState(true);
  const [showAngles, setShowAngles] = useState(true);
  const [showErrorRadii, setShowErrorRadii] = useState(false);

  const providerConnections = useMemo<DisplayConnectionDefinition[]>(
    () =>
      (stream?.skeleton_display_connections ?? []).map((connection) => ({
        startLandmark: connection.start_joint_name,
        endLandmark: connection.end_joint_name,
      })),
    [stream?.skeleton_display_connections],
  );

  // Publish the resolved subject so the pitch, metric tables and inspector
  // follow the same entity. Committing it durably keeps the view shareable.
  const selectSubject = context?.selectSubject;
  useEffect(() => {
    if (selectedSubject === null && subjectId !== null) {
      selectSubject?.(subjectId, { replace: true });
    }
  }, [selectSubject, selectedSubject, subjectId]);

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
  if (artifact.isPending || windowBounds === null || window.isPending) {
    return <LoadingPanel label="Loading pose window" />;
  }
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
        title={
          subjectId === null
            ? "No observed landmark is available in this window."
            : `Individual ${subjectId} is not observed at this time/window.`
        }
        detail="The selected identity remains unchanged; unavailable joints are never imputed or replaced."
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
        <span>
          individual <span className="mono text-text-secondary">{subjectId ?? "not scoped"}</span>
        </span>
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
        <div
          className="relative min-h-0 flex-1"
          data-testid="pose-canvas"
          data-renderer="r3f"
          data-renderer-ready={rendererReady ? "true" : "false"}
        >
          <Suspense fallback={<LoadingPanel label="Loading 3D renderer" />}>
            <PoseCanvas
              frames={frames}
              overlays={overlays}
              providerConnections={providerConnections}
              preset={preset}
              playing={playing}
              showProviderSkeleton={showProviderSkeleton}
              showTorsoCue={showTorsoCue}
              showFootContact={showFootContact}
              showHandContact={showHandContact}
              showHeadNeck={showHeadNeck}
              showArticulationAngles={showArticulationAngles}
              showSegments={showSegments}
              showAngles={showAngles}
              showErrorRadii={showErrorRadii}
              onReady={() => setRendererReady(true)}
            />
          </Suspense>
        </div>
        <aside className="w-60 shrink-0 overflow-y-auto border-l border-border-subtle bg-surface-1 p-2 text-[11px]">
          {observed.subjects.length > 0 ? (
            <div className="mb-3">
              <label
                htmlFor="pose-subject"
                className="t-section text-text-muted"
              >
                subject
              </label>
              <select
                id="pose-subject"
                value={subjectId ?? ""}
                onChange={(event) => context?.selectSubject(event.target.value)}
                className="mono mt-1 h-7 w-full rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[12px] text-text-secondary outline-none focus:border-accent"
              >
                {[...new Set(subjectId ? [...observed.subjects, subjectId] : observed.subjects)].map((candidate) => (
                  <option key={candidate} value={candidate}>
                    {candidate}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-text-muted">
                {observed.subjects.length} individuals in the artifact/session authority;
                landmarks are never merged across subjects.
              </p>
            </div>
          ) : null}
          <div className="mb-2">
        <span className="t-section text-text-muted">camera</span>
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
              className="size-6 shrink-0"
              checked={showErrorRadii}
              onChange={(event) => setShowErrorRadii(event.target.checked)}
            />
            provider p90 predicted error radius
          </label>
          <div className="mb-3 space-y-1">
            <span className="t-section text-text-muted">layers</span>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showProviderSkeleton}
                onChange={(event) => setShowProviderSkeleton(event.target.checked)}
              />
              provider skeleton / landmark connections
            </label>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showSegments}
                onChange={(event) => setShowSegments(event.target.checked)}
              />
              analytical segments
            </label>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showTorsoCue}
                onChange={(event) => setShowTorsoCue(event.target.checked)}
              />
              view-only torso cue
            </label>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showFootContact}
                onChange={(event) => setShowFootContact(event.target.checked)}
              />
              foot contact triangles
            </label>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showHandContact}
                onChange={(event) => setShowHandContact(event.target.checked)}
              />
              hand thumb / pinky closures
            </label>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showHeadNeck}
                onChange={(event) => setShowHeadNeck(event.target.checked)}
              />
              head / neck completeness
            </label>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showArticulationAngles}
                onChange={(event) => setShowArticulationAngles(event.target.checked)}
              />
              view-only articulation angles
            </label>
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox"
                className="size-6 shrink-0"
                checked={showAngles}
                onChange={(event) => setShowAngles(event.target.checked)}
              />
              joint angles
            </label>
          </div>
          <div className="mb-3">
            <span className="t-section text-text-muted">
              viewer frame
            </span>
            <dl className="mt-1 space-y-0.5 text-[10px] leading-snug text-text-muted">
              <div className="flex justify-between gap-2">
                <dt>screen up</dt>
                <dd className="mono text-text-secondary">source z (centroid-relative)</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>screen depth</dt>
                <dd className="mono text-text-secondary">−source y (right-handed)</dd>
              </div>
            </dl>
            <p className="t-evidence mt-1">
              display R<sub>x</sub>(+90°): [x, y, z] → [x, z, −y]
            </p>
            <p className="mt-1 text-[10px] leading-relaxed text-text-muted">
              Display orientation only. Every served pose metric is computed from relative
              vectors, so the view carries no absolute height or pitch position.
            </p>
          </div>
          <div className="mb-2">
            <span className="t-section text-text-muted">
              provider structure
            </span>
            <p className="text-text-muted">
              {providerConnections.length} provider display connection(s) · landmark_set · no parent tree
            </p>
            <p className="text-[10px] text-text-muted">
              Shoulder-to-hip torso cue is display-only and not provider topology or processor anatomy.
            </p>
            <p className="text-[10px] text-text-muted">
              Foot/head/neck closures and articulation angle cues are display-only; processor angles remain separate.
            </p>
          </div>
          <div className="mb-2">
            <span className="t-section text-text-muted">
              processor overlays
            </span>
            <p className="text-text-muted">
              {overlays.source === "none"
                ? "none declared for this stream's processor revision"
                : `${overlays.segments.length} segment(s), ${overlays.angles.length} angle(s) from processor parameters`}
            </p>
          </div>
          <div className="mb-2">
            <span className="t-section text-text-muted">
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
            <span className="t-section text-text-muted">
              frame time
            </span>
            <p className="mono text-text-secondary">
              {currentTime !== null ? `${formatClockNs(currentTime)}` : "playhead unavailable"}
            </p>
          </div>
          {inspected ? (
            <div>
              <span className="t-section text-text-muted">
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
