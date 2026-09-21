import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { StatePanel } from "@/components/common/StatePanel";
import { extractFrames, frameIndexAt, landmarksAt, summarizeFrame } from "@/components/pose/pose-model";
import type { SessionDetail, StreamView } from "@/api/types";
import { artifactQuery, sessionQuery, windowQuery } from "@/lib/api/queries";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useAnalysisStore } from "@/lib/state/analysis";
import { stablePoseSubjects } from "@/components/pose/use-pose-subjects";
import { windowAround } from "@/lib/dense-window";
import { formatMetricValue } from "@/lib/measurement";
import type { LabSearch } from "@/lib/search";
import { cn } from "@/lib/cn";

/**
 * Session explorer: dataset → session → trial/stream navigation. It reads the
 * server state through Query and selection is durable URL context.
 */
export function Explorer() {
  const location = useRouterState({ select: (state) => state.location });
  const parts = location.pathname.split("/").filter(Boolean);
  const datasetId = parts[0] === "lab" ? (parts[1] ?? null) : null;
  const sessionId = parts[0] === "lab" ? (parts[2] ?? null) : null;
  const search = new URLSearchParams(location.searchStr ?? "");
  const selectedStream = search.get("stream");
  const selectedTrial = search.get("trial");
  const selectedView = search.get("view");

  if (!datasetId || !sessionId) {
    return (
      <StatePanel
        state="empty"
        title="No session open."
        detail="Choose a dataset and session in the Catalog to open the laboratory explorer."
      />
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-8 shrink-0 items-center border-b border-border-subtle px-3">
        <h2 className="t-section">
          Session explorer
        </h2>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ExplorerForSession
          datasetId={datasetId}
          sessionId={sessionId}
          selectedStream={selectedStream}
          selectedTrial={selectedTrial}
          selectedView={selectedView}
        />
      </div>
    </div>
  );
}

function ExplorerForSession({
  datasetId,
  sessionId,
  selectedStream,
  selectedTrial,
  selectedView,
}: {
  datasetId: string;
  sessionId: string;
  selectedStream: string | null;
  selectedTrial: string | null;
  selectedView: string | null;
}) {
  const query = useQuery(sessionQuery(datasetId, sessionId));
  const [trialsOpen, setTrialsOpen] = useState(true);
  const [streamsOpen, setStreamsOpen] = useState(true);
  const [filter, setFilter] = useState("");

  const handleTreeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLAnchorElement>("a[data-nav-item]"),
    );
    if (items.length === 0) return;
    event.preventDefault();
    const activeIndex = items.findIndex((item) => item === document.activeElement);
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const nextIndex = activeIndex < 0 ? 0 : Math.min(items.length - 1, Math.max(0, activeIndex + delta));
    items[nextIndex]?.focus();
  };

  if (query.isPending) {
    return <StatePanel state="loading" title="Loading session structure" />;
  }
  if (query.isError) {
    return <StatePanel state="error" title="Session could not be loaded." />;
  }
  const { participants, trials, streams } = query.data;
  const needle = filter.trim().toLowerCase();
  const visibleTrials = trials.filter((trial) =>
    `${trial.label ?? ""} ${trial.trial_id}`.toLowerCase().includes(needle),
  );
  const visibleStreams = streams.filter((stream) =>
    `${stream.stream_id} ${stream.modality} ${stream.measurement_class}`
      .toLowerCase()
      .includes(needle),
  );
  return (
    <div className="p-2 text-[12px]" onKeyDown={handleTreeKeyDown}>
      <div className="mb-2 border-b border-border-subtle pb-2">
        <div className="mono truncate text-[11px] text-text-muted">{datasetId}</div>
        <div className="truncate text-text-secondary">{sessionId}</div>
        <div className="text-[11px] text-text-muted">
          {participants.length} participants · {trials.length} trials · {streams.length} streams
        </div>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter trials and streams"
          aria-label="Filter session structure"
          className="mt-1 h-6 w-full rounded-control border border-border-subtle bg-surface-0 px-2 text-[11px] outline-none focus:border-accent"
        />
      </div>

      <button
        type="button"
        onClick={() => setTrialsOpen((open) => !open)}
        className="t-section t-control-compact flex w-full items-center gap-1 py-1 text-text-muted hover:text-text-secondary"
      >
        {trialsOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />} Trials
      </button>
      {trialsOpen ? (
        <ul className="mb-2">
          {visibleTrials.map((trial) => (
            <li key={trial.trial_id}>
              <Link
                to="/lab/$datasetId/$sessionId"
                params={{ datasetId, sessionId }}
                data-nav-item
                search={(previous: LabSearch) => ({
                  ...previous,
                  trial: trial.trial_id,
                })}
                title={trial.label ? `${trial.trial_id} — ${trial.label}` : trial.trial_id}
                className={cn(
                  "flex min-w-0 flex-col rounded-control border-l-2 border-transparent px-2 py-1 transition-colors duration-quick hover:bg-surface-2",
                  selectedTrial === trial.trial_id &&
                    "border-accent bg-surface-3 text-text-primary",
                )}
              >
                {/*
                  Provider trial labels carry the whole condition and index
                  description; at explorer width they wrap into an unreadable
                  block, so the id leads and the label follows as one clipped
                  line with the full text on hover.
                */}
                <span className="mono truncate text-[11px] text-text-secondary">
                  {trial.trial_id}
                </span>
                {trial.label ? (
                  <span className="truncate text-[10px] text-text-muted">{trial.label}</span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}

      {selectedView === "pose" ? (
        <PoseTelemetry
          participants={participants}
          streams={streams}
          selectedStream={selectedStream}
        />
      ) : null}

      <button
        type="button"
        onClick={() => setStreamsOpen((open) => !open)}
        className="t-section t-control-compact flex w-full items-center gap-1 py-1 text-text-muted hover:text-text-secondary"
      >
        {streamsOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />} Streams
      </button>
      {streamsOpen ? (
        <ul>
          {visibleStreams.map((stream) => (
            <li key={stream.stream_id}>
              <Link
                to="/lab/$datasetId/$sessionId"
                params={{ datasetId, sessionId }}
                data-nav-item
                search={(previous: LabSearch) => ({
                  ...previous,
                  stream: stream.stream_id,
                  trial: stream.trial_id ?? previous.trial,
                })}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-control border-l-2 border-transparent px-2 py-1 transition-colors duration-quick hover:bg-surface-2",
                  selectedStream === stream.stream_id &&
                    "border-accent bg-surface-3 text-text-primary",
                )}
                title={`${stream.modality} · ${stream.measurement_class}`}
              >
                <span className="truncate">{stream.stream_id}</span>
                <span className="mono text-[10px] text-text-muted">
                  {stream.nominal_sampling_rate_hz ?? "?"} Hz
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function PoseTelemetry({
  participants,
  streams,
  selectedStream,
}: {
  participants: SessionDetail["participants"];
  streams: readonly StreamView[];
  selectedStream: string | null;
}) {
  const context = useAnalysisContext();
  const playheadNs = useAnalysisStore((state) => state.playheadNs);
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const stream = useMemo(
    () =>
      streams.find(
        (candidate) =>
          candidate.stream_id === selectedStream && candidate.modality === "pose",
      ) ?? streams.find((candidate) => candidate.modality === "pose") ?? null,
    [selectedStream, streams],
  );
  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({
    ...artifactQuery(artifactId ?? ""),
    enabled: Boolean(artifactId),
  });
  const subjects = useMemo(
    () => stablePoseSubjects(artifact.data, participants, stream?.subject_id ?? null),
    [artifact.data, participants, stream?.subject_id],
  );
  const subjectId = context?.subjectId ?? subjects[0] ?? stream?.subject_id ?? null;
  const effective = playheadNs ?? committedTimeNs;
  const bounds = useMemo(
    () =>
      windowAround(artifact.data, {
        anchorNs: effective,
        explicit: null,
        maxPoints: 20_000,
        entityScoped: subjectId !== null,
      }),
    [artifact.data, effective, subjectId],
  );
  const window = useQuery({
    ...windowQuery({
      artifactId: artifactId ?? "",
      ...(bounds ? { fromNs: Number(bounds.fromNs), toNs: Number(bounds.toNs) } : {}),
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
      maxPoints: 20_000,
    }),
    enabled: Boolean(artifactId) && bounds !== null,
  });
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

  if (stream === null || artifactId === null || artifact.isPending || window.isPending) {
    return null;
  }
  return (
    <section
      aria-label="Live pose telemetry"
      data-testid="pose-telemetry"
      className="mb-2 border-b border-border-subtle pb-2"
    >
      <div className="flex items-center justify-between gap-2 py-1">
        <span className="t-section text-text-muted">Live pose telemetry</span>
        <span className="mono text-[10px] text-text-secondary">{subjectId ?? "—"}</span>
      </div>
      <div className="mb-1 text-[10px] text-text-muted">
        {summary.observedLandmarks} observed · {summary.unavailableLandmarks} unavailable
      </div>
      <div className="max-h-80 overflow-y-auto rounded-control border border-border-subtle">
        {jointNames.map((jointName) => {
          const landmark = byName.get(jointName);
          return (
            <div
              key={jointName}
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-1 border-b border-border-subtle px-1.5 py-1 last:border-b-0"
            >
              <span className="mono truncate text-[10px] text-text-secondary">{jointName}</span>
              {landmark ? (
                <span className="mono text-right text-[9px] tabular text-text-muted">
                  {landmark.xM.toFixed(2)}, {landmark.yM.toFixed(2)}, {landmark.zM.toFixed(2)}
                  {landmark.errorM !== null
                    ? ` · ${formatMetricValue(landmark.errorM, "m").text}`
                    : ""}
                </span>
              ) : (
                <span className="text-[9px] text-quality-warning">unavailable</span>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
