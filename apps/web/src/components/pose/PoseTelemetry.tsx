import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { extractFrames, frameIndexAt, landmarksAt, summarizeFrame } from "@/components/pose/pose-model";
import { stablePoseSubjects } from "@/components/pose/use-pose-subjects";
import { useAnalysisContext } from "@/lib/analysis-context";
import { artifactQuery, sessionQuery } from "@/lib/api/queries";
import { affordableSpanNs, canonicalSpan } from "@/lib/dense-window";
import { usePosePlaybackWindow } from "@/components/pose/use-pose-playback";
import { formatMetricValue } from "@/lib/measurement";
import { useAnalysisStore } from "@/lib/state/analysis";

/** Full live landmark telemetry for the Pose route's right-hand evidence pane. */
export function PoseTelemetry() {
  const context = useAnalysisContext();
  const playheadNs = useAnalysisStore((state) => state.playheadNs);
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const session = useQuery({
    ...sessionQuery(context?.datasetId ?? "", context?.sessionId ?? ""),
    enabled: Boolean(context),
  });
  const stream = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === context?.streamId) ??
      streams.find((candidate) => candidate.modality === "pose") ??
      null;
  }, [context?.streamId, session.data?.streams]);
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
  const subjectId = context?.subjectId ?? subjects[0] ?? stream?.subject_id ?? null;
  const effective = playheadNs ?? committedTimeNs;
  const canonical = canonicalSpan(artifact.data);
  const chunkSpanNs = useMemo(
    () => affordableSpanNs(artifact.data, {
      maxPoints: 20_000,
      entityScoped: subjectId !== null,
    }),
    [artifact.data, subjectId],
  );
  const playback = usePosePlaybackWindow({
    artifactId,
    entityId: subjectId,
    canonicalMinNs: canonical?.minNs ?? null,
    canonicalMaxNs: canonical?.maxNs ?? null,
    chunkSpanNs,
    anchorNs: committedTimeNs,
    maxPoints: 20_000,
  });
  const { window } = playback;
  const frames = useMemo(
    () =>
      extractFrames(
        (window.data?.rows ?? []) as Array<{ [key: string]: unknown }>,
        subjectId,
      ),
    [subjectId, window.data],
  );
  const landmarks = landmarksAt(frames, effective);
  const byName = new Map(landmarks.map((landmark) => [landmark.jointName, landmark]));
  const jointNames = stream?.skeleton_joint_names ?? landmarks.map((landmark) => landmark.jointName);
  const frameIndex = effective === null ? 0 : frameIndexAt(frames, effective);
  const summary = summarizeFrame(
    frames.length > 0 && frameIndex >= 0 ? frames[frameIndex] ?? null : null,
  );

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
    <aside aria-label="Live pose telemetry" data-testid="pose-telemetry" className="flex h-full min-h-0 flex-col bg-surface-1">
      <header className="shrink-0 border-b border-border-subtle px-3 py-2">
        <h2 className="t-section text-text-muted">Live pose telemetry</h2>
        <p className="mono mt-1 text-[12px] text-text-primary">{subjectId ?? "not scoped"}</p>
        <p className="mt-1 text-[10px] text-text-muted">
          {summary.observedLandmarks} observed · {summary.unavailableLandmarks} unavailable
        </p>
      </header>
      <div
        aria-label="Pose landmark telemetry table"
        className="min-h-0 flex-1 overflow-y-auto p-2"
        tabIndex={0}
      >
        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 border-b border-border-subtle px-1.5 py-1 text-[10px] text-text-muted">
          <span>landmark</span>
          <span>x · y · z · p90 radius</span>
        </div>
        {jointNames.map((jointName) => {
          const landmark = byName.get(jointName);
          return (
            <div
              key={jointName}
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 border-b border-border-subtle px-1.5 py-1.5 last:border-b-0"
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
      </div>
    </aside>
  );
}

export default PoseTelemetry;
