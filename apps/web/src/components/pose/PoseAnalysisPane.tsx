import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { MetricValue } from "@/api/types";
import { EMPTY_JOINT_NAMES } from "@/components/pose/pose-model";
import { PoseTelemetry } from "@/components/pose/PoseTelemetry";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useMatchFrameContext } from "@/lib/match-frame-context";
import {
  artifactQuery,
  metricsQuery,
  methodologyQuery,
  processingArtifactsQuery,
  sessionQuery,
} from "@/lib/api/queries";
import { decodeWindowOffThread } from "@/lib/arrow/client";
import type { DecodedWindow } from "@/lib/arrow/decode";
import { fetchWindowArrowPrepared } from "@/lib/api/arrow-window";
import { windowAround } from "@/lib/dense-window";
import { useThrottledPlayhead } from "@/hooks/useThrottledPlayhead";
import { formatMetricValue } from "@/lib/measurement";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatClockNs } from "@/lib/time";
import { stablePoseSubjects } from "@/components/pose/use-pose-subjects";

const SECTIONS = [
  "Live",
  "Selected joint",
  "Range",
  "Symmetry",
  "Kinematics",
  "Quality",
  "Method / Provenance",
  "Raw landmarks",
] as const;

type Section = (typeof SECTIONS)[number];
type WaveMetric = "body_relative_speed" | "relative_position_x" | "path_length";

const WAVE_METRICS: readonly { readonly id: WaveMetric; readonly label: string; readonly unit: string }[] = [
  { id: "body_relative_speed", label: "Body-relative speed", unit: "m/s" },
  { id: "relative_position_x", label: "Body-relative X", unit: "m" },
  { id: "path_length", label: "Path length", unit: "m" },
];

const PRECOMPUTED_LANDMARKS = new Set(["lHip", "rHip", "lKnee", "rKnee", "lAnkle", "rAnkle"]);

function landmarkToken(name: string): string {
  return name.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function metricValue(metric: MetricValue): string {
  if (metric.value_num === null) return "—";
  return formatMetricValue(metric.value_num, metric.si_unit).text;
}

function MetricRows({ rows, empty }: { readonly rows: readonly MetricValue[]; readonly empty: string }) {
  if (rows.length === 0) {
    return <p className="px-3 py-4 text-[11px] text-text-muted">{empty}</p>;
  }
  return (
    <dl className="divide-y divide-border-subtle">
      {rows.map((row) => (
        <div key={row.derived_metric_id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-3 py-2">
          <div className="min-w-0">
            <dt className="truncate text-[11px] text-text-secondary">{row.metric_name ?? row.metric_id}</dt>
            <dd className="mono truncate text-[9px] text-text-muted">{row.metric_id}</dd>
          </div>
          <dd className="mono self-center text-right text-[11px] tabular text-text-primary">
            {metricValue(row)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function PoseAnalysisPane() {
  const context = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
  const [section, setSection] = useState<Section>("Live");
  const [waveMetric, setWaveMetric] = useState<WaveMetric>("body_relative_speed");
  const throttledTimeNs = useThrottledPlayhead(200);
  const selectedJoint = useAnalysisStore((state) => state.selectedJoint);
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);

  const session = useQuery({
    ...sessionQuery(context?.datasetId ?? "", context?.sessionId ?? ""),
    enabled: Boolean(context?.datasetId && context?.sessionId),
  });
  const stream = useMemo(() => {
    const streams = session.data?.streams ?? [];
    const requested = streams.find((candidate) => candidate.stream_id === context?.streamId) ?? null;
    if (requested?.modality === "pose") return requested;
    if (requested?.modality !== "tracking") return null;
    const trialId = context?.trialId ?? requested.trial_id;
    return streams.find(
      (candidate) => candidate.modality === "pose" && candidate.trial_id === trialId,
    ) ?? null;
  }, [context?.streamId, context?.trialId, session.data?.streams]);
  const sourceArtifactId = stream?.sample_artifact_ids[0] ?? null;
  const sourceArtifact = useQuery({
    ...artifactQuery(sourceArtifactId ?? ""),
    enabled: Boolean(sourceArtifactId),
  });
  const subjects = useMemo(
    () => stablePoseSubjects(sourceArtifact.data, session.data?.participants ?? [], stream?.subject_id ?? null),
    [session.data?.participants, sourceArtifact.data, stream?.subject_id],
  );
  const subjectId =
    matchFrame?.selectedPlayerId ?? context?.subjectId ?? subjects[0] ?? stream?.subject_id ?? null;
  const participant = session.data?.participants.find((item) => item.subject_id === subjectId) ?? null;
  const jointNames = stream?.skeleton_joint_names ?? EMPTY_JOINT_NAMES;
  const currentTimeNs = throttledTimeNs ?? committedTimeNs ?? context?.timeNs ?? null;

  const metrics = useQuery({
    ...metricsQuery({
      datasetId: context?.datasetId ?? undefined,
      sessionId: context?.sessionId ?? undefined,
      trialId: context?.trialId ?? undefined,
      streamId: stream?.stream_id ?? undefined,
      subjectId: subjectId ?? undefined,
      entityId: subjectId ?? undefined,
      limit: 1000,
    }),
    enabled: Boolean(context?.datasetId && context?.sessionId && stream?.stream_id),
  });
  const metricRows = useMemo(() => metrics.data?.rows ?? [], [metrics.data?.rows]);
  const processingArtifacts = useQuery({
    ...processingArtifactsQuery({
      datasetId: context?.datasetId ?? "",
      sessionId: context?.sessionId,
      streamId: stream?.stream_id,
    }),
    enabled: Boolean(context?.datasetId && context?.sessionId && stream?.stream_id),
  });
  const landmarkArtifact = processingArtifacts.data?.find(
    (artifact) =>
      artifact.algorithm_id === "pose.landmark_kinematics" &&
      artifact.artifact_metadata?.series_name === "pose_landmark_kinematics",
  );
  const landmarkArtifactDetail = useQuery({
    ...artifactQuery(landmarkArtifact?.artifact_id ?? ""),
    enabled: Boolean(landmarkArtifact?.artifact_id),
  });
  const dropoutArtifact = processingArtifacts.data?.find(
    (artifact) =>
      artifact.algorithm_id === "pose.analysis_quality" &&
      artifact.artifact_metadata?.series_name === "pose_quality_dropout_intervals",
  );
  const dropoutArtifactDetail = useQuery({
    ...artifactQuery(dropoutArtifact?.artifact_id ?? ""),
    enabled: Boolean(dropoutArtifact?.artifact_id),
  });

  const routeFromNs = context?.fromNs ?? null;
  const routeToNs = context?.toNs ?? null;
  const explicitRange = useMemo(() => {
    if (committedRangeNs !== null) return committedRangeNs;
    if (routeFromNs !== null && routeToNs !== null) {
      return { fromNs: routeFromNs, toNs: routeToNs };
    }
    return null;
  }, [committedRangeNs, routeFromNs, routeToNs]);
  const landmarkSpan = useMemo(
    () =>
      windowAround(landmarkArtifactDetail.data, {
        anchorNs: committedTimeNs ?? context?.timeNs ?? null,
        explicit: explicitRange,
        maxPoints: 2000,
        entityScoped: true,
      }),
    [committedTimeNs, context?.timeNs, explicitRange, landmarkArtifactDetail.data],
  );
  const dropoutSpan = useMemo(
    () =>
      windowAround(dropoutArtifactDetail.data, {
        anchorNs: committedTimeNs ?? context?.timeNs ?? null,
        explicit: explicitRange,
        maxPoints: 5000,
        entityScoped: true,
      }),
    [committedTimeNs, context?.timeNs, dropoutArtifactDetail.data, explicitRange],
  );
  const selectedToken = selectedJoint === null ? null : landmarkToken(selectedJoint);
  const waveformColumn = selectedToken === null
    ? null
    : waveMetric === "body_relative_speed"
      ? `body_relative_speed_${selectedToken}_m_s`
      : waveMetric === "relative_position_x"
        ? `relative_position_x_${selectedToken}_m`
        : `path_length_${selectedToken}_m`;
  const canLoadWaveform =
    landmarkArtifact !== undefined &&
    selectedJoint !== null &&
    PRECOMPUTED_LANDMARKS.has(selectedJoint) &&
    landmarkSpan !== null &&
    waveformColumn !== null &&
    subjectId !== null;
  const waveform = useQuery({
    queryKey: [
      "pose-analysis-series-window",
      landmarkArtifact?.artifact_id ?? null,
      subjectId,
      selectedJoint,
      waveMetric,
      landmarkSpan?.fromNs.toString() ?? null,
      landmarkSpan?.toNs.toString() ?? null,
    ],
    queryFn: ({ signal }) =>
      fetchWindowArrowPrepared(
        landmarkArtifact!.artifact_id,
        {
          fromNs: Number(landmarkSpan!.fromNs),
          toNs: Number(landmarkSpan!.toNs),
          columns: [waveformColumn!],
          maxPoints: 2000,
          entityId: subjectId!,
        },
        decodeWindowOffThread,
        signal,
        async (decoded) => decoded,
      ),
    enabled: canLoadWaveform,
    staleTime: 30_000,
  });
  const dropoutWindow = useQuery({
    queryKey: [
      "pose-analysis-dropout-window",
      dropoutArtifact?.artifact_id ?? null,
      subjectId,
      selectedJoint,
      dropoutSpan?.fromNs.toString() ?? null,
      dropoutSpan?.toNs.toString() ?? null,
    ],
    queryFn: ({ signal }) =>
      fetchWindowArrowPrepared(
        dropoutArtifact!.artifact_id,
        {
          fromNs: Number(dropoutSpan!.fromNs),
          toNs: Number(dropoutSpan!.toNs),
          columns: ["t_rel_ns", "joint_name", "start_ns", "end_ns_exclusive", "missing_frames", "duration_s"],
          maxPoints: 5000,
          entityId: subjectId!,
        },
        decodeWindowOffThread,
        signal,
        async (decoded) => decoded,
      ),
    enabled: Boolean(dropoutArtifact?.artifact_id && dropoutSpan && selectedJoint && subjectId),
    staleTime: 30_000,
  });

  const rowsForSelectedJoint = useMemo(() => {
    if (selectedToken === null) return [];
    const angleToken = selectedJoint?.startsWith("l")
      ? `left_${selectedJoint.slice(1, 2).toLowerCase()}${selectedJoint.slice(2)}`
      : selectedJoint?.startsWith("r")
        ? `right_${selectedJoint.slice(1, 2).toLowerCase()}${selectedJoint.slice(2)}`
        : "";
    return metricRows.filter(
      (row) => row.metric_id.endsWith(`.${selectedToken}`) || (angleToken !== "" && row.metric_id.endsWith(`.${angleToken}`)),
    );
  }, [metricRows, selectedJoint, selectedToken]);
  const kinematicsRows = useMemo(
    () => metricRows.filter((row) => /^(pose\.landmark\.|pose\.segment_|pose\.angular_)/.test(row.metric_id)),
    [metricRows],
  );
  const qualityRows = useMemo(
    () => metricRows.filter((row) => row.metric_id.startsWith("pose.quality.") || row.metric_id.startsWith("pose.availability.") || row.metric_id.startsWith("pose.error_radius_")),
    [metricRows],
  );
  const symmetryRows = useMemo(
    () => metricRows.filter((row) => row.metric_id.startsWith("pose.bilateral.")),
    [metricRows],
  );
  const methodologyMetricId = rowsForSelectedJoint[0]?.metric_id ?? metricRows[0]?.metric_id ?? "";
  const methodology = useQuery({
    ...methodologyQuery(methodologyMetricId),
    enabled: Boolean(methodologyMetricId),
  });
  const decodedWaveform = waveform.data?.prepared;
  const waveformPath = waveformColumn === null ? null : waveformPathFor(decodedWaveform, waveformColumn);
  const selectedDropouts = useMemo(
    () => dropoutIntervalsFor(dropoutWindow.data?.prepared, selectedJoint),
    [dropoutWindow.data?.prepared, selectedJoint],
  );
  const sourceCoverage = metricRows.find((row) => row.metric_id === "pose.quality.coverage.any_usable_pose");
  const tabId = (item: Section) => `pose-analysis-tab-${item.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  const panelId = "pose-analysis-active-panel";

  if (context === null) {
    return <div className="p-3 text-[11px] text-text-muted">Open a Pose or MatchLab session to inspect analysis.</div>;
  }
  if (session.isPending || sourceArtifact.isPending) {
    return <div className="p-3 text-[11px] text-text-muted">Loading Pose analysis context…</div>;
  }
  if (stream === null || sourceArtifactId === null) {
    return <div className="p-3 text-[11px] text-quality-warning">Pose analysis is unavailable for this stream.</div>;
  }

  return (
    <aside aria-label="Pose analysis pane" data-testid="pose-analysis-pane" className="flex h-full min-h-0 flex-col bg-surface-1">
      <header className="shrink-0 border-b border-border-subtle px-3 py-2">
        <h2 className="t-section text-text-muted">Pose analysis</h2>
        <p className="mt-1 truncate text-[12px] text-text-primary">
          {participant?.notes ?? subjectId ?? "No subject selected"}
          {participant?.notes && subjectId ? <span className="mono ml-1.5 text-[10px] text-text-muted">{subjectId}</span> : null}
        </p>
        <p className="mono mt-0.5 text-[10px] tabular text-text-muted">
          {currentTimeNs === null ? "No canonical time" : formatClockNs(currentTimeNs)}
          {selectedJoint ? ` · ${selectedJoint}` : " · select a joint"}
        </p>
        {sourceCoverage?.value_num !== null && sourceCoverage?.value_num !== undefined ? (
          <p className="mt-1 text-[10px] text-text-muted">
            Stream usable-Pose coverage {formatMetricValue(sourceCoverage.value_num, "1").text}
          {jointNames.length > 0 ? ` · ${jointNames.length} registered landmarks` : ""}
          </p>
        ) : null}
      </header>
      <div role="tablist" aria-label="Pose analysis sections" className="flex shrink-0 flex-wrap gap-1 border-b border-border-subtle px-2 py-1.5">
        {SECTIONS.map((item) => (
          <button
            key={item}
            id={tabId(item)}
            type="button"
            role="tab"
            aria-selected={section === item}
            aria-controls={panelId}
            onClick={() => setSection(item)}
            className={section === item
              ? "shrink-0 rounded-sm border border-border-subtle bg-surface-3 px-2 py-1 text-[10px] text-text-primary"
              : "shrink-0 rounded-sm px-2 py-1 text-[10px] text-text-muted hover:bg-surface-2 hover:text-text-secondary"}
          >
            {item}
          </button>
        ))}
      </div>
      <div id={panelId} role="tabpanel" aria-labelledby={tabId(section)} className="min-h-0 flex-1 overflow-y-auto">
        {section === "Live" ? (
          <div className="flex h-full min-h-0 flex-col">
            <PoseTelemetry summaryOnly />
            <div className="border-t border-border-subtle px-3 py-2">
              <p className="text-[10px] text-text-muted">
                Source/model-estimated landmarks and provider p90 error-radius evidence stay separate from pipeline metrics.
              </p>
            </div>
          </div>
        ) : null}
        {section === "Selected joint" ? (
          <div className="flex flex-col">
            <label className="px-3 py-2 text-[10px] text-text-muted">
              Selected landmark
              <select
                aria-label="Select Pose landmark"
                className="mono mt-1 block w-full rounded-sm border border-border-subtle bg-surface-0 px-2 py-1.5 text-[11px] text-text-primary"
                value={selectedJoint ?? ""}
                onChange={(event) => useAnalysisStore.getState().selectJoint(event.currentTarget.value || null)}
              >
                <option value="">Choose a landmark</option>
                {jointNames.map((name) => <option key={name} value={name}>{name}</option>)}
              </select>
            </label>
            <MetricRows rows={rowsForSelectedJoint} empty="No processor summary is registered for this landmark in the selected stream." />
            <div className="border-t border-border-subtle px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="t-section text-text-muted">Precomputed waveform</h3>
                <select
                  aria-label="Select Pose waveform"
                  className="rounded-sm border border-border-subtle bg-surface-0 px-1.5 py-1 text-[10px] text-text-secondary"
                  value={waveMetric}
                  onChange={(event) => setWaveMetric(event.currentTarget.value as WaveMetric)}
                >
                  {WAVE_METRICS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
              </div>
              {!selectedJoint || !PRECOMPUTED_LANDMARKS.has(selectedJoint) ? (
                <p className="mt-2 text-[10px] text-text-muted">This landmark is available as source evidence; its body-relative waveform is not in the current accepted processor selection.</p>
              ) : processingArtifacts.isError || (processingArtifacts.isSuccess && landmarkArtifact === undefined) ? (
                <p className="mt-2 text-[10px] text-quality-warning">No current landmark-kinematics series is served for this Pose stream.</p>
              ) : waveform.isPending ? (
                <p className="mt-2 text-[10px] text-text-muted">Loading bounded processor series…</p>
              ) : waveform.isError ? (
                <p className="mt-2 text-[10px] text-quality-warning">The processor series is unavailable for this time window.</p>
              ) : waveformPath === null ? (
                <p className="mt-2 text-[10px] text-text-muted">No valid samples in this exact window.</p>
              ) : (
                <figure className="mt-2" aria-label={`${selectedJoint} ${WAVE_METRICS.find((item) => item.id === waveMetric)?.label ?? "metric"} waveform`}>
                  <svg viewBox="0 0 100 36" role="img" aria-hidden="true" className="h-24 w-full overflow-visible rounded-sm border border-border-subtle bg-surface-0 p-1">
                    <path d={waveformPath} fill="none" stroke="currentColor" strokeWidth="0.8" className="text-accent" vectorEffect="non-scaling-stroke" />
                  </svg>
                  <figcaption className="mt-1 text-[9px] text-text-muted">
                    {waveform.data?.meta.reduction ? "Display-reduced precomputed series" : "Exact precomputed processor series"}
                    {" · "}{waveform.data?.prepared.rowCount ?? 0} points · {WAVE_METRICS.find((item) => item.id === waveMetric)?.unit}
                  </figcaption>
                </figure>
              )}
            </div>
          </div>
        ) : null}
        {section === "Range" ? (
          <div className="px-3 py-3">
            <h3 className="t-section text-text-muted">Selected canonical range</h3>
            {explicitRange ? (
              <p className="mono mt-2 text-[10px] tabular text-text-secondary">
                {formatClockNs(explicitRange.fromNs)} – {formatClockNs(explicitRange.toNs)}
              </p>
            ) : (
              <p className="mt-2 text-[10px] text-text-muted">No committed range. Use the shared timeline to brush and commit an exact range.</p>
            )}
            <p className="mt-3 text-[10px] text-text-muted">
              The waveform above reads the precomputed exact-time series for the selected window. Scalar values below are the processor’s registered stream-span summaries.
            </p>
            <MetricRows rows={kinematicsRows} empty="No accepted geometric or derivative summaries are available." />
          </div>
        ) : null}
        {section === "Symmetry" ? (
          <MetricRows rows={symmetryRows} empty="No aligned bilateral geometric comparison is available for this stream." />
        ) : null}
        {section === "Kinematics" ? (
          <MetricRows rows={kinematicsRows} empty="No accepted geometric or derivative summaries are available." />
        ) : null}
        {section === "Quality" ? (
          <div>
            <MetricRows rows={qualityRows} empty="Pose quality and coverage summaries are unavailable for this stream." />
            <section aria-label="Selected landmark dropout timeline" className="border-t border-border-subtle px-3 py-3">
              <h3 className="t-section text-text-muted">Dropouts · {selectedJoint ?? "select a landmark"}</h3>
              {selectedJoint === null ? (
                <p className="mt-2 text-[10px] text-text-muted">Select a landmark to inspect its processor dropout intervals.</p>
              ) : dropoutArtifact === undefined || dropoutArtifactDetail.isError ? (
                <p className="mt-2 text-[10px] text-quality-warning">No time-indexed dropout interval series is served for this Pose stream.</p>
              ) : dropoutWindow.isPending ? (
                <p className="mt-2 text-[10px] text-text-muted">Loading bounded dropout intervals…</p>
              ) : dropoutWindow.isError || dropoutArtifact === undefined ? (
                <p className="mt-2 text-[10px] text-quality-warning">Dropout intervals are unavailable for this stream.</p>
              ) : selectedDropouts.length === 0 ? (
                <p className="mt-2 text-[10px] text-text-muted">No dropout intervals for this landmark in the selected time window.</p>
              ) : (
                <ul className="mt-2 divide-y divide-border-subtle">
                  {selectedDropouts.slice(0, 12).map((interval) => (
                    <li key={`${interval.startNs}-${interval.endNsExclusive}`} className="flex justify-between gap-2 py-1.5 text-[10px]">
                      <span className="mono text-text-secondary">
                        {formatClockNs(interval.startNs)}–{formatClockNs(interval.endNsExclusive)} · {interval.missingFrames} frames
                      </span>
                      <span className="mono text-text-muted">{interval.durationS.toFixed(2)} s</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        ) : null}
        {section === "Method / Provenance" ? (
          <div className="px-3 py-3">
            {methodology.data?.algorithm ? (
              <dl className="space-y-2 text-[10px]">
                <div><dt className="text-text-muted">Algorithm</dt><dd className="mono text-text-secondary">{methodology.data.algorithm.algorithm_id} · v{methodology.data.algorithm.version}</dd></div>
                <div><dt className="text-text-muted">Code SHA</dt><dd className="mono break-all text-text-secondary">{methodology.data.algorithm.code_git_sha ?? "unavailable"}</dd></div>
                <div><dt className="text-text-muted">Parameters hash</dt><dd className="mono break-all text-text-secondary">{methodology.data.algorithm.parameters_hash ?? "unavailable"}</dd></div>
                <div><dt className="text-text-muted">Definition</dt><dd className="text-text-secondary">{methodology.data.metric.description ?? methodology.data.algorithm.description ?? "No description served."}</dd></div>
                <div><dt className="text-text-muted">Measurement class</dt><dd className="text-text-secondary">{methodology.data.metric.measurement_class}</dd></div>
              </dl>
            ) : (
              <p className="text-[10px] text-text-muted">{methodology.isPending ? "Loading method and provenance…" : "No selected metric method is registered."}</p>
            )}
          </div>
        ) : null}
        {section === "Raw landmarks" ? <PoseTelemetry /> : null}
      </div>
    </aside>
  );
}

function waveformPathFor(decoded: DecodedWindow | undefined, columnName: string): string | null {
  const column = decoded?.columns.find((candidate) => candidate.name === columnName);
  if (decoded === undefined || column === undefined || !(column.values instanceof Float64Array)) return null;
  const values = column.values;
  let minimum = Number.POSITIVE_INFINITY;
  let maximum = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    minimum = Math.min(minimum, value);
    maximum = Math.max(maximum, value);
  }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return null;
  const span = maximum - minimum || 1;
  const commands: string[] = [];
  let open = false;
  for (let index = 0; index < values.length; index += 1) {
    const value = values[index]!;
    if (!Number.isFinite(value)) {
      open = false;
      continue;
    }
    const x = values.length <= 1 ? 0 : (index / (values.length - 1)) * 100;
    const y = 32 - ((value - minimum) / span) * 28;
    commands.push(`${open ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`);
    open = true;
  }
  return commands.join(" ");
}

interface PoseDropoutInterval {
  readonly startNs: bigint;
  readonly endNsExclusive: bigint;
  readonly missingFrames: number;
  readonly durationS: number;
}

function dropoutIntervalsFor(
  decoded: DecodedWindow | undefined,
  selectedJoint: string | null,
): PoseDropoutInterval[] {
  if (decoded === undefined || selectedJoint === null) return [];
  const joints = decoded.columns.find((column) => column.name === "joint_name")?.values;
  const starts = decoded.columns.find((column) => column.name === "start_ns")?.values;
  const ends = decoded.columns.find((column) => column.name === "end_ns_exclusive")?.values;
  const missing = decoded.columns.find((column) => column.name === "missing_frames")?.values;
  const durations = decoded.columns.find((column) => column.name === "duration_s")?.values;
  if (
    !Array.isArray(joints) ||
    !(starts instanceof Float64Array) ||
    !(ends instanceof Float64Array) ||
    !(missing instanceof Float64Array) ||
    !(durations instanceof Float64Array)
  ) return [];
  const intervals: PoseDropoutInterval[] = [];
  for (let index = 0; index < decoded.rowCount; index += 1) {
    if (joints[index] !== selectedJoint) continue;
    const start = starts[index];
    const end = ends[index];
    const missingFrames = missing[index];
    const durationS = durations[index];
    if (start === undefined || end === undefined || missingFrames === undefined || durationS === undefined) continue;
    if (![start, end, missingFrames, durationS].every(Number.isFinite)) continue;
    intervals.push({
      startNs: BigInt(Math.trunc(start)),
      endNsExclusive: BigInt(Math.trunc(end)),
      missingFrames,
      durationS,
    });
  }
  return intervals;
}

export default PoseAnalysisPane;
