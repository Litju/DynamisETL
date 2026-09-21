import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { CopyableId } from "@/components/common/CopyableId";
import { UPlotSignal } from "@/components/charts/UPlotSignal";
import {
  defaultGroupId,
  groupChannels,
  type ChannelGroup,
} from "@/components/charts/signal-channels";
import {
  reductionNote,
  type SignalBand,
  type SignalPane,
  type SignalSeries,
} from "@/components/charts/signal-model";
import { useDenseWindow } from "@/components/lab/use-dense-window";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { MetricValue, StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { artifactQuery, metricsQuery, sessionQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import {
  bandPointsFor,
  originNs,
  pointsFor,
  populatedBandPairs,
  populatedMeasures,
  type WindowTable,
} from "@/lib/arrow/window-table";
import { formatMetricValue } from "@/lib/measurement";
import {
  resolveSignalStream,
  stableIndividualIds,
} from "@/lib/individual-selection";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatDurationNs, nsFromRendererTime, rendererTimeMs } from "@/lib/time";

const MAX_WINDOW_POINTS = 4000;
const RANGE_COMMIT_DEBOUNCE_MS = 250;

/**
 * What the canonical clock of a stream counts from. Only clocks whose
 * reference this project declares are named; anything else stays unqualified
 * rather than asserting an origin the source does not document.
 */
const CLOCK_REFERENCE: Readonly<Record<string, string>> = {
  "white-takeoff-relative": "takeoff",
  "skillcorner-match-clock": "period start",
};

/**
 * Signal laboratory: bounded, display-reduced analytical windows over a
 * canonical or processor-derived stream artifact. Dense transport prefers Arrow
 * IPC decoded in a worker; JSON remains the metadata fallback. Playback updates
 * go straight to the chart instance, never through React state.
 */
export function SignalLaboratory() {
  const context = useAnalysisContext();
  const datasetId = context?.datasetId ?? null;
  const sessionId = context?.sessionId ?? null;
  const streamId = context?.streamId ?? null;
  const fromNs = context?.fromNs ?? null;
  const toNs = context?.toNs ?? null;

  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const currentStream: StreamView | null = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === streamId) ?? null;
  }, [session.data, streamId]);
  const selectedSubject = context?.subjectId ?? null;
  const stream = useMemo(
    () =>
      resolveSignalStream(
        session.data?.streams ?? [],
        currentStream,
        selectedSubject,
      ),
    [currentStream, selectedSubject, session.data?.streams],
  );
  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({
    ...artifactQuery(artifactId ?? ""),
    enabled: Boolean(artifactId),
  });
  const individuals = useMemo(
    () => stableIndividualIds(artifact.data, session.data?.streams ?? []),
    [artifact.data, session.data?.streams],
  );
  const subjectId = selectedSubject ?? stream?.subject_id ?? individuals[0] ?? null;
  const entityId = artifact.data?.entity_column
    ? subjectId ?? undefined
    : undefined;

  // Selecting a subject on a per-subject stream resolves to the compatible
  // real stream/trial and makes that resolution durable for reloads.
  useEffect(() => {
    if (selectedSubject === null && subjectId !== null) {
      context?.selectSubject(subjectId, { replace: true });
    }
    if (
      selectedSubject !== null &&
      currentStream !== null &&
      stream !== null &&
      stream.stream_id !== currentStream.stream_id
    ) {
      context?.selectStream(stream.stream_id);
    }
  }, [context, currentStream, selectedSubject, stream, subjectId]);
  const dense = useDenseWindow({
    artifactId,
    ...(fromNs !== null ? { fromNs: Number(fromNs) } : {}),
    ...(toNs !== null ? { toNs: Number(toNs) } : {}),
    ...(entityId !== undefined ? { entityId } : {}),
    maxPoints: MAX_WINDOW_POINTS,
  });

  if (!context) {
    return <StatePanel state="empty" title="Open a laboratory session first." />;
  }
  if (session.isPending) {
    return <LoadingPanel label="Loading session streams" />;
  }
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }
  if (streamId === null) {
    return (
      <StatePanel
        state="empty"
        title="No stream selected."
        detail="Select a stream in the explorer to load its bounded signal window."
      />
    );
  }
  if (stream === null) {
    return (
      <StatePanel
        state="unavailable"
        title={
          selectedSubject === null
            ? "Stream is not part of this session."
            : `No signal stream is available for individual ${selectedSubject}.`
        }
        detail="The selected identity remains unchanged; another subject's stream is never substituted."
      />
    );
  }
  if (artifactId === null) {
    return (
      <StatePanel
        state="unavailable"
        title="No canonical artifact is registered for this stream."
        detail="Run the deterministic ingest path to materialize canonical Parquet before analysis."
      />
    );
  }
  if (dense.isError) {
    const error = dense.error;
    if (error instanceof ApiError && error.state === "dense_window_too_large") {
      return (
        <StatePanel
          state="blocked"
          title="Dense window too large."
          detail="Narrow the time range in the transport or select a shorter trial before requesting this window."
        />
      );
    }
    return <ErrorPanel error={error} onRetry={() => void dense.refetch()} />;
  }
  if (dense.isPending || dense.data.table === null) {
    return <LoadingPanel label="Loading dense window" />;
  }
  return (
      <SignalView
        stream={stream}
        individuals={individuals}
        subjectId={subjectId}
        artifactId={artifactId}
      table={dense.data.table}
      transport={dense.data.transport ?? "json"}
      fromNs={fromNs}
      toNs={toNs}
    />
  );
}

function SignalView({
  stream,
  individuals,
  subjectId,
  artifactId,
  table,
  transport,
  fromNs,
  toNs,
}: {
  stream: StreamView;
  individuals: readonly string[];
  subjectId: string | null;
  artifactId: string;
  table: WindowTable;
  transport: "arrow" | "json";
  fromNs: bigint | null;
  toNs: bigint | null;
}) {
  const context = useAnalysisContext();
  const commitTimer = useRef<number | null>(null);
  const measurementClass = table.meta.artifact.measurement_class ?? stream.measurement_class;
  const origin = useMemo(() => originNs(table), [table]);
  // Only quantities this window actually observed: a schema column that is
  // all null is not a measurement the laboratory can offer.
  const measures = useMemo(() => populatedMeasures(table), [table]);
  const bands = useMemo(() => populatedBandPairs(table), [table]);
  const unitMap = table.meta.units;
  const reductionText = reductionNote(table.meta);

  // Channels are grouped by physical quantity so a body-weight ratio never
  // shares a value axis with a moment in newton metres.
  const groups = useMemo(() => {
    const columns = bands.length > 0 ? bands.map((band) => band.base) : measures;
    return groupChannels(columns, unitMap);
  }, [bands, measures, unitMap]);

  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const activeGroupId = useMemo(() => {
    if (selectedGroupId !== null && groups.some((group) => group.id === selectedGroupId)) {
      return selectedGroupId;
    }
    return defaultGroupId(groups, stream.modality);
  }, [groups, selectedGroupId, stream.modality]);
  const activeGroup = groups.find((group) => group.id === activeGroupId) ?? null;

  const panes: SignalPane[] = useMemo(
    () =>
      activeGroup === null
        ? []
        : [{ id: activeGroup.id, label: activeGroup.label, unit: activeGroup.unit }],
    [activeGroup],
  );

  const allRowIndexes = useMemo(
    () => Array.from({ length: table.rowCount }, (_value, index) => index),
    [table.rowCount],
  );

  const series = useMemo<SignalSeries[]>(() => {
    if (activeGroup === null || bands.length > 0) return [];
    return activeGroup.channels
      .filter((channel) => measures.includes(channel.id))
      .map((channel) => ({
        name: channel.label,
        unit: channel.unit,
        measurementClass,
        paneIndex: 0,
        points: pointsFor(table, channel.id, allRowIndexes, origin),
      }));
  }, [activeGroup, allRowIndexes, bands.length, measurementClass, measures, origin, table]);

  const bandSeries = useMemo<SignalBand[]>(() => {
    if (activeGroup === null) return [];
    const wanted = new Set(activeGroup.channels.map((channel) => channel.id));
      return bands
      .filter((band) => wanted.has(band.base))
      .map((band) => ({
        name: activeGroup.channels.find((channel) => channel.id === band.base)?.label ?? band.base,
        base: band.base,
        unit: unitMap[band.base] ?? unitMap[band.minKey] ?? "1",
        measurementClass,
        paneIndex: 0,
        points: bandPointsFor(table, band.minKey, band.maxKey, origin),
      }));
  }, [activeGroup, bands, measurementClass, origin, table, unitMap]);

  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const rangeNs = useAnalysisStore((state) => state.committedRangeNs);
  const committedPlayheadMs =
    committedTimeNs === null ? null : rendererTimeMs(origin, committedTimeNs);
  const timeReference = CLOCK_REFERENCE[stream.clock_id];

  useEffect(() => {
    return () => {
      if (commitTimer.current !== null) window.clearTimeout(commitTimer.current);
    };
  }, []);

  const handlePointClick = useCallback(
    (selection: { xMs: number }) => {
      if (!Number.isFinite(selection.xMs)) return;
      const tNs = nsFromRendererTime(origin, selection.xMs);
      useAnalysisStore.getState().setPlayhead(tNs);
      context?.commitTime(tNs);
    },
    [context, origin],
  );

  const handleRangeZoom = useCallback(
    (selection: { fromMs: number; toMs: number }) => {
      const range = {
        fromNs: nsFromRendererTime(origin, selection.fromMs),
        toNs: nsFromRendererTime(origin, selection.toMs),
      };
      useAnalysisStore.getState().setBrushRange(range);
      if (commitTimer.current !== null) window.clearTimeout(commitTimer.current);
      commitTimer.current = window.setTimeout(() => {
        context?.commitRange(range);
      }, RANGE_COMMIT_DEBOUNCE_MS);
    },
    [context, origin],
  );

  const hasTrace = series.length > 0 || bandSeries.length > 0;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <AnalysisHeader
          stream={stream}
          individuals={individuals}
          subjectId={subjectId}
          group={activeGroup}
          groups={groups}
          onSelectGroup={setSelectedGroupId}
        />
        <div className="min-h-0 flex-1">
          {hasTrace ? (
            <UPlotSignal
              ariaLabel={`${activeGroup?.label ?? "Signal"} for ${stream.stream_id}`}
              panes={panes}
              series={series}
              bands={bandSeries}
              originNs={origin}
              {...(timeReference !== undefined ? { timeReference } : {})}
              playheadMs={committedPlayheadMs}
              rangeMs={
                rangeNs === null
                  ? null
                  : {
                      fromMs: rendererTimeMs(origin, rangeNs.fromNs),
                      toMs: rendererTimeMs(origin, rangeNs.toNs),
                    }
              }
              onPointClick={handlePointClick}
              onRangeZoom={handleRangeZoom}
            />
          ) : (
            <StatePanel
              state="empty"
              title="No numeric measure is present in this window."
              detail="Identity and flag columns are never plotted; select another stream or widen the range."
            />
          )}
        </div>
        <ProvenanceStrip
          stream={stream}
          artifactId={artifactId}
          table={table}
          transport={transport}
          fromNs={fromNs}
          toNs={toNs}
          reductionText={reductionText}
        />
      </div>
      <TrialEvidence stream={stream} subjectId={subjectId} />
    </div>
  );
}

/**
 * The analysis title and the quantity selector. What is plotted, for whom, in
 * what units — before any identifier.
 */
function AnalysisHeader({
  stream,
  individuals,
  subjectId,
  group,
  groups,
  onSelectGroup,
}: {
  stream: StreamView;
  individuals: readonly string[];
  subjectId: string | null;
  group: ChannelGroup | null;
  groups: readonly ChannelGroup[];
  onSelectGroup: (groupId: string) => void;
}) {
  const context = useAnalysisContext();
  return (
    <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="t-analysis-title">
          {group?.label ?? "Signal window"}
          {group && group.unit !== "1" ? (
            <span className="ml-2 text-[12px] font-normal text-text-muted">[{group.unit}]</span>
          ) : null}
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
      {individuals.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <label htmlFor="signal-individual" className="text-[11px] text-text-muted">
            individual
          </label>
          <select
            id="signal-individual"
            value={subjectId ?? ""}
            onChange={(event) => context?.selectSubject(event.target.value)}
            className="mono h-7 rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[11px] text-text-secondary outline-none focus:border-accent"
          >
            {[...new Set(subjectId ? [...individuals, subjectId] : individuals)].map((individual) => (
              <option key={individual} value={individual}>
                {individual}
              </option>
            ))}
          </select>
          <span className="text-[10px] text-text-muted">
            selected identity scopes the dense request and evidence
          </span>
        </div>
      ) : subjectId !== null ? (
        <p className="mt-1 text-[10px] text-text-muted">
          individual <span className="mono text-text-secondary">{subjectId}</span>
        </p>
      ) : null}
      {groups.length > 1 ? (
        <div
          role="group"
          aria-label="Plotted quantity"
          className="mt-1.5 flex flex-wrap items-center gap-1"
        >
          {groups.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              aria-pressed={candidate.id === group?.id}
              onClick={() => onSelectGroup(candidate.id)}
              className={cn(
                "rounded-control border px-2 py-0.5 text-[11px] transition-colors duration-quick",
                candidate.id === group?.id
                  ? "border-accent bg-surface-3 text-text-primary"
                  : "border-border-subtle text-text-muted hover:border-border-strong hover:text-text-secondary",
              )}
            >
              {candidate.label}
            </button>
          ))}
        </div>
      ) : null}
    </header>
  );
}

/**
 * Transport, window extent and reduction state. Exactness is a scientific
 * property of the view, so it is stated next to the plot, not buried.
 */
function ProvenanceStrip({
  stream,
  artifactId,
  table,
  transport,
  fromNs,
  toNs,
  reductionText,
}: {
  stream: StreamView;
  artifactId: string;
  table: WindowTable;
  transport: "arrow" | "json";
  fromNs: bigint | null;
  toNs: bigint | null;
  reductionText: string | null;
}) {
  const spanNs =
    fromNs !== null && toNs !== null
      ? toNs - fromNs
      : table.meta.canonical_time_max_ns !== null && table.meta.canonical_time_min_ns !== null
        ? BigInt(table.meta.canonical_time_max_ns) - BigInt(table.meta.canonical_time_min_ns)
        : null;
  return (
    <footer className="shrink-0 border-t border-border-subtle bg-surface-1 px-4 py-1.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-text-muted">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-[3px] border px-1.5 py-px",
            reductionText
              ? "border-quality-warning text-quality-warning"
              : "border-quality-valid text-quality-valid",
          )}
          title={
            reductionText ??
            "Every plotted point is a canonical sample; no display reduction was applied."
          }
        >
          <span aria-hidden="true">{reductionText ? "▲" : "●"}</span>
          {reductionText ? "Display-reduced" : "Exact samples"}
        </span>
        <span className="tabular">
          {table.meta.source_rows.toLocaleString("en-US")} source rows →{" "}
          {table.meta.returned_rows.toLocaleString("en-US")} plotted
        </span>
        {spanNs !== null ? <span className="tabular">{formatDurationNs(spanNs)} window</span> : null}
        <span>
          Frame <span className="text-text-secondary">{stream.coordinate_frame_id ?? "unavailable"}</span>
        </span>
        <span>
          Sync <span className="text-text-secondary">{stream.synchronization_spec_id}</span>
        </span>
        <span className="ml-auto flex items-center gap-2">
          <span title="Dense transport actually used for this window">{transport} transport</span>
          <CopyableId value={artifactId} label="artifact id" className="max-w-56" />
        </span>
      </div>
      {reductionText ? (
        <p className="mt-1 text-[10px] leading-relaxed text-quality-warning">
          The shaded band is the per-bucket min/max envelope of the reduction, not measured
          uncertainty. Metric values never derive from it.
        </p>
      ) : null}
    </footer>
  );
}

/**
 * Real derived metrics for the plotted trial, beside the trace they describe.
 * Selecting one drives the inspector, so the value and its method stay linked.
 */
function TrialEvidence({
  stream,
  subjectId,
}: {
  stream: StreamView;
  subjectId: string | null;
}) {
  const context = useAnalysisContext();
  const metrics = useQuery({
    ...metricsQuery({
      datasetId: context?.datasetId ?? undefined,
      sessionId: context?.sessionId ?? undefined,
      ...(subjectId ? { subjectId } : {}),
      ...(stream.trial_id ? { trialId: stream.trial_id } : {}),
      limit: 60,
    }),
    enabled: Boolean(context),
  });
  const artifactId = stream.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({
    ...artifactQuery(artifactId ?? ""),
    enabled: Boolean(artifactId),
  });
  const selectedResult = context?.derivedMetricId ?? null;

  const rows = metrics.data?.rows ?? [];

  return (
    <aside
      aria-label="Trial evidence"
      className="flex w-72 shrink-0 flex-col border-l border-border-subtle bg-surface-1"
    >
      <div className="shrink-0 border-b border-border-subtle px-3 py-2">
        <h3 className="t-analysis-title text-text-secondary">
          {stream.trial_id ? "Trial" : "Stream"}
        </h3>
        <p className="mono mt-0.5 truncate text-[11px] text-text-muted" title={stream.trial_id ?? stream.stream_id}>
          {stream.trial_id ?? stream.stream_id}
        </p>
        <dl className="mt-2 space-y-1 text-[11px]">
          <EvidenceRow label="Individual" value={subjectId ?? stream.subject_id ?? "not subject-scoped"} />
          <EvidenceRow
            label="Samples"
            value={stream.sample_row_count.toLocaleString("en-US")}
          />
          {artifact.data?.canonical_time_min_ns !== null &&
          artifact.data?.canonical_time_min_ns !== undefined &&
          artifact.data.canonical_time_max_ns !== null &&
          artifact.data.canonical_time_max_ns !== undefined ? (
            <EvidenceRow
              label="Canonical span"
              value={formatDurationNs(
                BigInt(artifact.data.canonical_time_max_ns) -
                  BigInt(artifact.data.canonical_time_min_ns),
              )}
            />
          ) : null}
        </dl>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <h3 className="t-section sticky top-0 z-10 bg-surface-1 px-3 pb-1 pt-2 text-text-muted">
          Derived metrics
        </h3>
        {metrics.isPending ? (
          <p className="px-3 py-2 text-[11px] text-text-muted">Loading metrics…</p>
        ) : metrics.isError ? (
          <ErrorPanel error={metrics.error} onRetry={() => void metrics.refetch()} />
        ) : rows.length === 0 ? (
          <p className="px-3 py-2 text-[11px] leading-relaxed text-text-muted">
            No derived metric is served for this trial. Metrics appear after the deterministic
            processor and Gold rebuild path runs.
          </p>
        ) : (
          <ul className="pb-2">
            {rows.map((metric) => (
              <li key={metric.derived_metric_id}>
                <MetricEvidenceRow
                  metric={metric}
                  selected={metric.derived_metric_id === selectedResult}
                  onSelect={() => context?.selectResult(metric.derived_metric_id)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="shrink-0 text-text-muted">{label}</dt>
      <dd className="mono min-w-0 truncate text-right text-text-secondary" title={value}>
        {value}
      </dd>
    </div>
  );
}

function MetricEvidenceRow({
  metric,
  selected,
  onSelect,
}: {
  metric: MetricValue;
  selected: boolean;
  onSelect: () => void;
}) {
  const display = formatMetricValue(metric.value_num, metric.si_unit);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      title={`${metric.metric_id}\nExact value: ${metric.value_num ?? "unavailable"} ${metric.si_unit}`}
      className={cn(
        "flex w-full items-baseline justify-between gap-2 border-l-2 px-3 py-1.5 text-left transition-colors duration-quick hover:bg-surface-2",
        selected ? "border-accent bg-surface-2" : "border-transparent",
      )}
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12px] text-text-secondary">
          {metric.metric_name ?? metric.metric_id}
        </span>
        <span className="mono block truncate text-[10px] text-text-muted">
          {metric.metric_id}
        </span>
      </span>
      <span className="mono shrink-0 whitespace-nowrap text-[12px] tabular text-text-primary">
        {display.text}
      </span>
    </button>
  );
}
