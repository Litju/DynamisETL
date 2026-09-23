import { useQuery } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import {
  CAMERA_MODES,
  extractFrames,
  frameIndexAt,
  groupFramesBySubject,
  landmarksAt,
  NO_OVERLAYS,
  overlaysFromParameters,
  summarizeFrame,
  type DisplayConnectionDefinition,
  type PoseSubjectFrames,
  type PoseLandmark,
} from "@/components/pose/pose-model";
import type { StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { artifactQuery, methodologyQuery, metricsQuery, sessionQuery } from "@/lib/api/queries";
import {
  firstPoseObservationInRange,
  fetchPoseObservationsInRange,
  usePoseSubjects,
} from "@/components/pose/use-pose-subjects";
import { affordableSpanNs, canonicalSpan } from "@/lib/dense-window";
import {
  retirePoseSubjectQueries,
  usePosePlaybackWindow,
} from "@/components/pose/use-pose-playback";
import { INITIAL_POSE_VIEW, poseViewReducer } from "@/components/pose/pose-view-state";
import { useThrottledPlayhead } from "@/hooks/useThrottledPlayhead";
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
  const queryClient = useQueryClient();
  const datasetId = context?.datasetId ?? null;
  const sessionId = context?.sessionId ?? null;
  const streamId = context?.streamId ?? null;
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  // Read-outs follow a throttled playhead; the 3D hot path reads the store
  // directly, so playback never re-renders this component per frame.
  const throttledTimeNs = useThrottledPlayhead(200);
  const playing = useAnalysisStore((state) => state.playing);
  const subjectSwitching = useAnalysisStore((state) => state.subjectSwitching);
  const switchingFromSubjectId = useAnalysisStore((state) => state.switchingFromSubjectId);
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  const hoveredJoint = useAnalysisStore((state) => state.hoveredJoint);
  const [rendererReady, setRendererReady] = useState(false);
  const [view, dispatchView] = useReducer(poseViewReducer, INITIAL_POSE_VIEW);
  const allSubjects = view.scope === "all";
  const coordinateMode = view.frame;
  const cameraMode = view.camera;
  const [pausedBySwitch, setPausedBySwitch] = useState(false);
  useEffect(() => useAnalysisStore.subscribe((state, previous) => {
    if (state.playing && !previous.playing) setPausedBySwitch(false);
  }), []);
  const subjectSwitchRequest = useRef(0);
  const subjectSwitchAbort = useRef<AbortController | null>(null);
  const [subjectSwitchError, setSubjectSwitchError] = useState<string | null>(null);

  useEffect(() => () => subjectSwitchAbort.current?.abort(), []);

  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const stream: StreamView | null = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === streamId) ?? null;
  }, [session.data, streamId]);

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
  const participantLabel = (candidate: string) => {
    const participant = session.data?.participants.find((item) => item.subject_id === candidate);
    const name = participant?.notes ?? null;
    return name ? `${name}${participant?.cohort ? ` · ${participant.cohort}` : ""} — ${candidate}` : candidate;
  };
  const selectedSubject = context?.subjectId ?? null;
  const streamSubject = stream?.subject_id ?? null;
  const subjectId = useMemo(() => {
    if (selectedSubject !== null) return selectedSubject;
    return observedSubjectList[0] ?? streamSubject;
  }, [observedSubjectList, selectedSubject, streamSubject]);
  const subjectObservation = observed.observations.find((item) => item.entityId === subjectId);
  const subjectPlaybackEnabled =
    !subjectSwitching ||
    (switchingFromSubjectId !== null && switchingFromSubjectId !== subjectId);
  const previousSubject = useRef({ artifactId, subjectId });
  useEffect(() => {
    if (subjectSwitching) return;
    const previous = previousSubject.current;
    previousSubject.current = { artifactId, subjectId };
    if (previous.artifactId === artifactId && previous.subjectId !== subjectId) {
      retirePoseSubjectQueries(queryClient, artifactId, previous.subjectId);
    }
  }, [artifactId, queryClient, subjectId, subjectSwitching]);
  useEffect(() => {
    if (!subjectSwitching) return;
    const previous = previousSubject.current;
    retirePoseSubjectQueries(queryClient, previous.artifactId, previous.subjectId);
  }, [queryClient, subjectSwitching]);

  const explicitFromNs = context?.fromNs ?? null;
  const explicitToNs = context?.toNs ?? null;
  const artifactData = artifact.data;
  const sceneSubjectId = allSubjects ? null : subjectId;
  const canonical = canonicalSpan(artifactData);
  const chunkSpanNs = useMemo(
    () => affordableSpanNs(artifactData, {
      maxPoints: MAX_POSE_POINTS,
      entityScoped: sceneSubjectId !== null,
    }),
    [artifactData, sceneSubjectId],
  );
  const playback = usePosePlaybackWindow({
    enabled: subjectPlaybackEnabled,
    artifactId,
    entityId: sceneSubjectId,
    canonicalMinNs: canonical?.minNs ?? null,
    canonicalMaxNs: canonical?.maxNs ?? null,
    chunkSpanNs,
    anchorNs: committedTimeNs,
    explicitFromNs,
    explicitToNs,
    maxPoints: MAX_POSE_POINTS,
  });
  const { window, activeWindowBounds, playbackStatus } = playback;
  useEffect(() => {
    if (
      !subjectSwitching ||
      switchingFromSubjectId === null ||
      subjectId === switchingFromSubjectId ||
      context?.subjectId !== subjectId
    ) return;
    if (
      context?.timeNs === null ||
      context?.timeNs !== committedTimeNs ||
      artifact.isPending ||
      window.isPending ||
      window.isPlaceholderData ||
      window.data?.meta.reduction !== null
    ) return;
    useAnalysisStore.getState().finishSubjectSwitch();
  }, [artifact.isPending, committedTimeNs, context, subjectId, subjectSwitching, switchingFromSubjectId, window.data, window.isPending, window.isPlaceholderData]);
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
        sceneSubjectId,
      ),
    [sceneSubjectId, window.data],
  );
  const subjectFrames = useMemo<PoseSubjectFrames[]>(
    () => (allSubjects ? groupFramesBySubject(frames) : []),
    [allSubjects, frames],
  );
  const selectedFrames = useMemo(
    () =>
      allSubjects
        ? subjectFrames.find((candidate) => candidate.subjectId === subjectId)?.frames ?? []
        : frames,
    [allSubjects, frames, subjectFrames, subjectId],
  );
  const overlays = useMemo(
    () =>
      methodology.data?.algorithm
        ? overlaysFromParameters(methodology.data.algorithm.parameters)
        : NO_OVERLAYS,
    [methodology.data],
  );

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

  const handleSubjectChange = async (nextSubjectId: string) => {
    if (nextSubjectId === subjectId) return;
    subjectSwitchAbort.current?.abort();
    const controller = new AbortController();
    subjectSwitchAbort.current = controller;
    const requestId = ++subjectSwitchRequest.current;
    setSubjectSwitchError(null);
    const observation = observed.observations.find((item) => item.entityId === nextSubjectId);
    const fallbackTimeNs = context?.timeNs ?? committedTimeNs ?? canonical?.minNs ?? null;
    if (fallbackTimeNs === null) return;
    // RES-109 §12: a switch stops playback; say so instead of stopping silently.
    setPausedBySwitch(useAnalysisStore.getState().playing);
    useAnalysisStore.getState().beginSubjectSwitch(subjectId);
    let resolvedObservation = observation;
    if (
      artifactId !== null &&
      observation !== undefined &&
      firstPoseObservationInRange(observation, context?.fromNs ?? null, context?.toNs ?? null) === null
    ) {
      try {
        const rangeObservations = await fetchPoseObservationsInRange(
          artifactId,
          context?.fromNs ?? null,
          context?.toNs ?? null,
          controller.signal,
        );
        resolvedObservation = rangeObservations.find((item) => item.entityId === nextSubjectId);
      } catch {
        if (requestId !== subjectSwitchRequest.current) return;
        useAnalysisStore.getState().finishSubjectSwitch();
        subjectSwitchAbort.current = null;
        setSubjectSwitchError("Could not resolve Pose observations. The previous subject is restored; select again to retry.");
        return;
      }
    }
    if (requestId !== subjectSwitchRequest.current) return;
    const targetTimeNs =
      firstPoseObservationInRange(
        resolvedObservation,
        context?.fromNs ?? null,
        context?.toNs ?? null,
      ) ?? fallbackTimeNs;
    useAnalysisStore.getState().beginSubjectSwitch(subjectId, targetTimeNs);
    context?.selectSubject(nextSubjectId, { targetTimeNs });
    subjectSwitchAbort.current = null;
  };

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
  if (artifact.isPending || activeWindowBounds === null || window.isPending) {
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
  if (subjectSwitching) {
    return (
      <StatePanel
        state="loading"
        title="Switching subject…"
        detail="Stopping playback, retiring the previous subject and loading an exact replacement frame."
      />
    );
  }
  const hasSubjectFrames = selectedFrames.length > 0;
  const hasRenderableScene = allSubjects
    ? subjectFrames.some((candidate) => candidate.frames.some((frame) => frame.observed))
    : frames.some((frame) => frame.observed);
  if (!hasSubjectFrames && !hasRenderableScene) {
    const noObservationInRange =
      subjectObservation === undefined ||
      subjectObservation.observationCount === 0 ||
      (context.fromNs !== null && subjectObservation.lastObservedNs < context.fromNs) ||
      (context.toNs !== null && subjectObservation.firstObservedNs > context.toNs);
    return (
      <StatePanel
        state="unavailable"
        title={
          subjectId === null
            ? "No observed landmark is available in this window."
            : noObservationInRange
              ? `No Pose observations for subject ${subjectId} in ${context.trialId ?? "the selected period/range"}.`
              : `Subject ${subjectId} is not observed at ${context.timeNs ?? committedTimeNs
                ? formatClockNs((context.timeNs ?? committedTimeNs) as bigint)
                : "the current time"}.`
        }
        detail={
          noObservationInRange
            ? "The selected identity remains selected; this subject has no exact Pose observation in the active range."
            : subjectObservation
              ? `First observation ${formatClockNs(subjectObservation.firstObservedNs)} · last ${formatClockNs(subjectObservation.lastObservedNs)}.`
              : "The selected identity remains unchanged; unavailable joints are never imputed or replaced."
        }
      />
    );
  }

  const currentTime = throttledTimeNs;
  const currentLandmarks = landmarksAt(selectedFrames, currentTime);
  const currentFrameIndex = currentTime === null ? 0 : frameIndexAt(selectedFrames, currentTime);
  const summary = summarizeFrame(
    currentFrameIndex >= 0 ? (selectedFrames[currentFrameIndex] ?? null) : null,
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
        {allSubjects ? (
          <span>all subjects · fixed camera ({subjectFrames.length})</span>
        ) : (
          <span>
            individual <span className="mono text-text-secondary">{subjectId ?? "not scoped"}</span>
          </span>
        )}
        <span className="text-quality-warning">
          {coordinateMode === "body_local"
            ? "local analytical frame · Z is player-centroid-relative, not absolute height · body-root recentered for display"
            : "match/world frame · source XY placement preserved; Z remains provider-relative, not ground height"}
        </span>
        {pausedBySwitch && !playing ? (
          <span role="status" className="text-text-secondary">
            Playback paused for the subject switch — press Play to continue.
          </span>
        ) : null}
        {playbackStatus === "buffering" && playing ? (
          <span data-testid="playback-buffering" className="text-quality-warning">BUFFERING · waiting for exact next chunk</span>
        ) : null}
        {hasSubjectFrames ? (
          <span className="tabular">
            {summary.observedLandmarks} observed · {summary.unavailableLandmarks} unavailable
          </span>
        ) : (
          <span className="text-quality-warning">
            Subject {subjectId ?? "not scoped"} not observed at the current frame
          </span>
        )}
        {hasSubjectFrames && summary.meanErrorM !== null ? (
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
          role="img"
          aria-label={
            allSubjects
              ? `Pose world: ${subjectFrames.length} subjects in the match/world frame, subject ${subjectId ?? "none"} highlighted${currentTime !== null ? ` at ${formatClockNs(currentTime)}` : ""}`
              : `Pose skeleton of subject ${subjectId ?? "none"} in the ${coordinateMode === "body_local" ? "body-local" : "match/world"} frame${currentTime !== null ? ` at ${formatClockNs(currentTime)}` : ""}: ${summary.observedLandmarks} landmarks observed, ${summary.unavailableLandmarks} unavailable`
          }
        >
          <Suspense fallback={<LoadingPanel label="Loading 3D renderer" />}>
            <PoseCanvas
              frames={frames}
              subjectFrames={subjectFrames}
              allSubjects={allSubjects}
              overlays={overlays}
              providerConnections={providerConnections}
              preset="reset"
              cameraMode={cameraMode}
              coordinateMode={coordinateMode}
              onManualCamera={() => dispatchView({ type: "manual" })}
              selectedSubjectId={subjectId}
              onSelectSubject={(nextSubjectId) => void handleSubjectChange(nextSubjectId)}
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
            <ControlSection title="Subject">
              <select
                id="pose-subject"
                aria-label="Pose subject"
                value={subjectId ?? ""}
                onChange={(event) => handleSubjectChange(event.target.value)}
                className="t-control w-full rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[12px] text-text-secondary outline-none focus:border-accent"
              >
                {[...new Set(subjectId ? [...observed.subjects, subjectId] : observed.subjects)].map((candidate) => (
                  <option key={candidate} value={candidate}>
                    {participantLabel(candidate)}
                  </option>
                ))}
              </select>
              {subjectSwitchError ? (
                <p role="alert" className="mt-1 text-[10px] text-quality-warning">
                  {subjectSwitchError}
                </p>
              ) : null}
              <p className="mt-1 text-[10px] text-text-muted">
                {observed.subjects.length} individuals in the artifact/session authority; landmarks are never
                merged across subjects.
              </p>
            </ControlSection>
          ) : null}
          <ControlSection title="Scope">
            <div role="group" aria-label="Pose scope" className="grid grid-cols-2 gap-1">
              <SegmentButton pressed={!allSubjects} onClick={() => dispatchView({ type: "scope", scope: "subject" })}>
                selected subject
              </SegmentButton>
              <SegmentButton
                testId="pose-all-subjects-toggle"
                pressed={allSubjects}
                onClick={() => dispatchView({ type: "scope", scope: allSubjects ? "subject" : "all" })}
              >
                all subjects
              </SegmentButton>
            </div>
            <p className="mt-1 text-[10px] text-text-muted">
              {allSubjects
                ? `${subjectFrames.length} subjects share one source-coordinate world; the selected subject is highlighted and the others are context. Click a figure to select it.`
                : "One identity, recentred or placed in the source world."}
            </p>
          </ControlSection>
          <ControlSection title="Coordinate frame">
            <div role="group" aria-label="Pose coordinate authority" className="grid grid-cols-2 gap-1">
              <SegmentButton
                testId="pose-body-local-mode"
                pressed={coordinateMode === "body_local"}
                disabled={allSubjects}
                title={allSubjects ? "Body-local recentring is per subject; the all-subject world uses match/world placement." : undefined}
                onClick={() => dispatchView({ type: "frame", frame: "body_local" })}
              >
                body-local
              </SegmentButton>
              <SegmentButton
                testId="pose-match-world-mode"
                pressed={coordinateMode === "match_world"}
                onClick={() => dispatchView({ type: "frame", frame: "match_world" })}
              >
                match/world
              </SegmentButton>
            </div>
            <p className="mt-1 text-[10px] text-text-muted">
              Body-local removes display-only root travel; match/world preserves source XY identity.
            </p>
          </ControlSection>
          <ControlSection title="Camera">
            <div role="group" aria-label="Camera ownership" className="flex flex-wrap gap-1">
              {CAMERA_MODES.map((candidate) => (
                <SegmentButton
                  key={candidate}
                  pressed={cameraMode === candidate}
                  onClick={() => dispatchView({ type: "camera", camera: candidate })}
                >
                  {candidate.replaceAll("_", "-")}
                </SegmentButton>
              ))}
              <button
                type="button"
                data-testid="pose-camera-reset"
                onClick={() => dispatchView({ type: "reset" })}
                className="t-control-compact rounded-control border border-border-subtle px-1.5 text-text-muted hover:border-border-strong hover:text-text-secondary"
              >
                reset
              </button>
            </div>
            <p className="mt-1 text-[10px] text-text-muted" data-testid="pose-camera-ownership">
              {cameraMode === "manual"
                ? "Manual: the camera is yours until you choose a mode or reset; automatic follow is off."
                : cameraMode === "follow_subject"
                  ? "Follow: the camera tracks the subject root; dragging hands control to manual."
                  : cameraMode === "joint_focus"
                    ? "Joint focus: the camera tracks the selected landmark."
                    : cameraMode === "all_subjects"
                      ? "Group view: fixed on the observed group; no follow."
                      : cameraMode === "world_fixed"
                        ? "World-fixed: the camera stays put in the source world."
                        : "Body-local: fixed three-quarter view of the recentred subject."}
            </p>
          </ControlSection>
          <ControlSection title="Layers">
            <div role="group" aria-label="Pose layers" className="space-y-0.5">
              <LayerSwitch label="skeleton connections" detail="provider" checked={showProviderSkeleton} onChange={setShowProviderSkeleton} />
              <LayerSwitch label="analytical segments" detail="processor" checked={showSegments} onChange={setShowSegments} />
              <LayerSwitch label="joint angles" detail="processor" checked={showAngles} onChange={setShowAngles} />
              <LayerSwitch label="articulation angles" detail="view-only" checked={showArticulationAngles} onChange={setShowArticulationAngles} />
              <LayerSwitch label="torso cue" detail="view-only" checked={showTorsoCue} onChange={setShowTorsoCue} />
              <LayerSwitch label="foot contact" detail="view-only" checked={showFootContact} onChange={setShowFootContact} />
              <LayerSwitch label="hand closures" detail="view-only" checked={showHandContact} onChange={setShowHandContact} />
              <LayerSwitch label="head / neck" detail="view-only" checked={showHeadNeck} onChange={setShowHeadNeck} />
              <LayerSwitch label="p90 error radius" detail="provider" checked={showErrorRadii} onChange={setShowErrorRadii} />
            </div>
          </ControlSection>
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

function ControlSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="mb-3 border-b border-border-subtle/60 pb-3 last:border-b-0">
      <h3 className="t-section mb-1.5 text-text-muted">{title}</h3>
      {children}
    </section>
  );
}

function SegmentButton({
  pressed,
  onClick,
  children,
  disabled = false,
  title,
  testId,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
  title?: string | undefined;
  testId?: string;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      aria-pressed={pressed}
      disabled={disabled}
      title={title}
      onClick={onClick}
      className={
        pressed
          ? "t-control-compact rounded-control border border-accent bg-surface-3 px-1.5 text-text-primary"
          : "t-control-compact rounded-control border border-border-subtle px-1.5 text-text-muted hover:border-border-strong hover:text-text-secondary disabled:cursor-not-allowed disabled:opacity-40"
      }
    >
      {children}
    </button>
  );
}

/** A layer switch: role=switch, state as text + track position, not colour alone. */
function LayerSwitch({
  label,
  detail,
  checked,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={`${label} (${detail})`}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center gap-2 rounded-control px-1 py-1 text-left hover:bg-surface-2"
    >
      <span
        aria-hidden="true"
        className={
          checked
            ? "relative inline-block h-3 w-5 shrink-0 rounded-full bg-accent"
            : "relative inline-block h-3 w-5 shrink-0 rounded-full border border-border-strong bg-surface-0"
        }
      >
        <span
          className={
            checked
              ? "absolute right-0.5 top-0.5 size-2 rounded-full bg-surface-0"
              : "absolute left-0.5 top-[1px] size-2 rounded-full bg-text-muted"
          }
        />
      </span>
      <span className="min-w-0 flex-1 truncate text-[11px] text-text-secondary">{label}</span>
      <span className="shrink-0 text-[9px] uppercase tracking-wide text-text-muted">{detail}</span>
    </button>
  );
}

export default PoseViewer;
