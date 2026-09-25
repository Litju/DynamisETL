import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  EMPTY_JOINT_NAMES,
  nextFrameIndexAt,
  poseFrameFromBuffersAt,
  poseFrameIndexAt,
  poseFramesFromBuffers,
  summarizeFrame,
} from "@/components/pose/pose-model";
import { maximumFrameAgeNs } from "@/components/pitch/pitch-model";
import { poseSubjectObservations, stablePoseSubjects } from "@/components/pose/use-pose-subjects";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useMatchFrameContext } from "@/lib/match-frame-context";
import { artifactQuery, sessionQuery } from "@/lib/api/queries";
import { affordableSpanNs, canonicalSpan } from "@/lib/dense-window";
import { usePosePlaybackWindow } from "@/components/pose/use-pose-playback";
import { useThrottledPlayhead } from "@/hooks/useThrottledPlayhead";
import { formatMetricValue } from "@/lib/measurement";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatClockNs } from "@/lib/time";

/** Full live landmark telemetry for the Pose route's right-hand evidence pane. */
export function PoseTelemetry({ summaryOnly = false }: { readonly summaryOnly?: boolean } = {}) {
  const context = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
  // 29 rows of text: refreshed at most five times per second during playback.
  const effective = useThrottledPlayhead(200);
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const subjectSwitching = useAnalysisStore((state) => state.subjectSwitching);
  const session = useQuery({
    ...sessionQuery(context?.datasetId ?? "", context?.sessionId ?? ""),
    enabled: Boolean(context),
  });
  const stream = useMemo(() => {
    const streams = session.data?.streams ?? [];
    const requested = streams.find((candidate) => candidate.stream_id === context?.streamId) ?? null;
    if (requested === null) return null;
    if (requested?.modality === "pose") return requested;
    if (requested.modality !== "tracking") return null;
    const trialId = context?.trialId ?? requested?.trial_id ?? null;
    return streams.find((candidate) =>
      candidate.modality === "pose" && (trialId === null || candidate.trial_id === trialId),
    ) ?? null;
  }, [context?.streamId, context?.trialId, session.data?.streams]);
  const maxGapNs = maximumFrameAgeNs(stream?.nominal_sampling_rate_hz);
  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({
    ...artifactQuery(artifactId ?? ""),
    enabled: Boolean(artifactId),
  });
  const subjects = useMemo(
    () =>
      stablePoseSubjects(
        artifact.data,
        session.data?.participants ?? [],
        stream?.subject_id ?? null,
      ),
    [artifact.data, session.data?.participants, stream?.subject_id],
  );
  const observations = useMemo(() => poseSubjectObservations(artifact.data), [artifact.data]);
  const subjectId =
    matchFrame?.selectedPlayerId ?? context?.subjectId ?? subjects[0] ?? stream?.subject_id ?? null;
  const subjectObservation = observations.find((item) => item.entityId === subjectId);
  const participant = session.data?.participants.find((item) => item.subject_id === subjectId) ?? null;
  const canonical = canonicalSpan(artifact.data);
  const chunkSpanNs = useMemo(
    () => affordableSpanNs(artifact.data, {
      maxPoints: 20_000,
      entityScoped: subjectId !== null,
    }),
    [artifact.data, subjectId],
  );
  const playback = usePosePlaybackWindow({
    enabled: stream?.modality === "pose",
    artifactId,
    entityId: subjectId,
    jointNames: stream?.skeleton_joint_names ?? EMPTY_JOINT_NAMES,
    canonicalMinNs: canonical?.minNs ?? null,
    canonicalMaxNs: canonical?.maxNs ?? null,
    chunkSpanNs,
    anchorNs: committedTimeNs,
    maxPoints: 20_000,
  });
  const { window } = playback;
  const frames = useMemo(
    () => summaryOnly ? [] : poseFramesFromBuffers(window.data?.prepared, subjectId),
    [subjectId, summaryOnly, window.data],
  );
  const frameIndex = poseFrameIndexAt(frames, effective, maxGapNs);
  const currentFrame = summaryOnly
    ? poseFrameFromBuffersAt(window.data?.prepared, subjectId, effective, maxGapNs)
    : frameIndex >= 0
      ? frames[frameIndex] ?? null
      : null;
  const landmarks = currentFrame?.landmarks ?? [];
  const byName = new Map(landmarks.map((landmark) => [landmark.jointName, landmark]));
  const jointNames = stream?.skeleton_joint_names ?? window.data?.prepared.jointNames ?? landmarks.map((landmark) => landmark.jointName);
  const previousFrameIndex = summaryOnly || effective === null
    ? -1
    : poseFrameIndexAt(frames, effective, Number.POSITIVE_INFINITY);
  const nextIndex = summaryOnly || effective === null ? -1 : nextFrameIndexAt(frames, effective);
  const previousFrame = previousFrameIndex >= 0 ? frames[previousFrameIndex] ?? null : null;
  const nextFrame = nextIndex >= 0 ? frames[nextIndex] ?? null : null;
  const summary = summarizeFrame(currentFrame);
  const status = subjectSwitching
    ? "Switching subject…"
    : currentFrame === null
      ? subjectObservation === undefined || subjectObservation.observationCount === 0
        ? `No Pose observations for subject ${subjectId ?? "not scoped"} in ${context?.trialId ?? "the selected period/range"}.`
        : `Subject ${subjectId} not observed at ${effective === null ? "the current time" : formatClockNs(effective)}.`
      : null;

  if (session.isSuccess && (stream === null || artifactId === null)) {
    return <div className="p-3 text-[11px] text-quality-warning">Pose telemetry unavailable.</div>;
  }
  if (session.isPending || artifact.isPending || window.isPending) {
    return <div className="p-3 text-[11px] text-text-muted">Loading pose telemetry…</div>;
  }
  if (session.isError || artifact.isError || window.isError) {
    return <div className="p-3 text-[11px] text-quality-warning">Pose telemetry unavailable.</div>;
  }

  return (
    <aside aria-label={summaryOnly ? "Current Pose sample" : "Live pose telemetry"} data-testid="pose-telemetry" className="flex h-full min-h-0 flex-col bg-surface-1">
      <header className="shrink-0 border-b border-border-subtle px-3 py-2">
        <h2 className="t-section text-text-muted">{summaryOnly ? "Current sample" : "Live pose telemetry"}</h2>
        <p className="mt-1 text-[12px] text-text-primary">
          {participant?.notes ?? subjectId ?? "not scoped"}
          {participant?.notes ? <span className="mono ml-1.5 text-[10px] text-text-muted">{subjectId}</span> : null}
        </p>
        {participant?.cohort ? <p className="text-[10px] text-text-muted">{participant.cohort}</p> : null}
        <p className="mono mt-0.5 text-[10px] tabular text-text-muted">{effective === null ? "—" : formatClockNs(effective)}</p>
        {status ? (
          <p data-testid="pose-telemetry-status" className="mt-1 text-[10px] text-quality-warning">
            {status}
          </p>
        ) : (
          <p className="mt-1 text-[10px] text-text-muted">
            {summary.observedLandmarks} observed · {summary.unavailableLandmarks} unavailable
          </p>
        )}
      </header>
      {summaryOnly ? null : <div
        aria-label="Pose landmark telemetry table"
        className="min-h-0 flex-1 overflow-y-auto p-2"
        tabIndex={0}
      >
        {status ? (
          <div className="p-2 text-[11px] text-text-muted">
            {subjectObservation && subjectObservation.observationCount > 0
              ? (previousFrame
                  ? "Previous source sample " + formatClockNs(BigInt(previousFrame.tRelNs)) + " · "
                  : "") +
                (nextFrame
                  ? "Next source sample " + formatClockNs(BigInt(nextFrame.tRelNs)) + " · "
                  : "") +
                "First observation " + formatClockNs(subjectObservation.firstObservedNs) +
                " · last " + formatClockNs(subjectObservation.lastObservedNs) + "."
              : "The selected identity remains selected; unavailable landmarks are not fabricated."}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 border-b border-border-subtle px-1.5 py-1 text-[10px] text-text-muted">
              <span>landmark</span>
              <span title="Provider source frame, metres; Z is player-centroid-relative">source x · y · z · p90 (m)</span>
            </div>
            {jointNames.map((jointName) => {
              const landmark = byName.get(jointName);
              return (
                <div
                  key={jointName}
                  aria-current={selectedJoint === jointName ? "true" : undefined}
                  className={
                    selectedJoint === jointName
                      ? "grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 border-b border-l-2 border-border-subtle border-l-accent bg-surface-3 px-1.5 py-1.5 last:border-b-0"
                      : "grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 border-b border-border-subtle px-1.5 py-1.5 last:border-b-0"
                  }
                >
                  <span className="mono truncate text-[11px] text-text-secondary">{jointName}</span>
                  {landmark ? (
                    <span className="mono text-right text-[10px] tabular text-text-muted">
                      {landmark.xM.toFixed(3)} · {landmark.yM.toFixed(3)} · {landmark.zM.toFixed(3)} · {landmark.errorM === null ? "—" : formatMetricValue(landmark.errorM, "m").text}
                    </span>
                  ) : (
                    <span className="text-[10px] text-quality-warning">unavailable</span>
                  )}
                </div>
              );
            })}
          </>
        )}
      </div>}
    </aside>
  );
}

export default PoseTelemetry;
