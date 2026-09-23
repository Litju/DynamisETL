import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { EChart } from "@/components/charts/EChart";
import {
  rankedMetricOption,
  zoneBreakdownOption,
  MAX_RANKED_ENTITIES,
} from "@/components/charts/overview-options";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { MetricValue, SessionDetail } from "@/api/types";
import { metricsQuery, sessionQuery } from "@/lib/api/queries";
import { readPalette } from "@/lib/chart-palette";
import { cn } from "@/lib/cn";
import { formatMetricValue } from "@/lib/measurement";
import { participantLabels } from "@/lib/participants";
import {
  entityKeyOf,
  headlineMetricId,
  leadingFact,
  rankMetric,
  zoneBreakdown,
} from "@/lib/overview-summaries";

const METRIC_PAGE_LIMIT = 1000;

/**
 * Session overview.
 *
 * The analytical summary leads and the contracts support it. Every chart plots
 * served Gold rows directly — a bar is one row — so selecting a mark carries
 * the same identity, method and provenance as selecting the row in the table
 * below it.
 */
export function LabOverview({
  datasetId,
  sessionId,
  streamFilter,
  selectedResult,
  onSelectStream,
  onSelectResult,
  onSelectSubject,
}: {
  datasetId: string;
  sessionId: string;
  streamFilter: string | null;
  selectedResult: string | null;
  onSelectStream: (streamId: string | null) => void;
  onSelectResult: (metricId: string, derivedMetricId: string) => void;
  onSelectSubject: (subjectId: string) => void;
}) {
  const session = useQuery(sessionQuery(datasetId, sessionId));
  const metrics = useQuery(
    metricsQuery({ datasetId, sessionId, limit: METRIC_PAGE_LIMIT }),
  );

  if (session.isPending || metrics.isPending) {
    return <LoadingPanel label="Loading session context" />;
  }
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }
  if (metrics.isError) {
    return <ErrorPanel error={metrics.error} onRetry={() => void metrics.refetch()} />;
  }

  return (
    <OverviewBody
      session={session.data}
      rows={metrics.data.rows}
      total={metrics.data.total}
      streamFilter={streamFilter}
      selectedResult={selectedResult}
      onSelectStream={onSelectStream}
      onSelectResult={onSelectResult}
      onSelectSubject={onSelectSubject}
    />
  );
}

function OverviewBody({
  session,
  rows,
  total,
  streamFilter,
  selectedResult,
  onSelectStream,
  onSelectResult,
  onSelectSubject,
}: {
  session: SessionDetail;
  rows: readonly MetricValue[];
  total: number;
  streamFilter: string | null;
  selectedResult: string | null;
  onSelectStream: (streamId: string | null) => void;
  onSelectResult: (metricId: string, derivedMetricId: string) => void;
  onSelectSubject: (subjectId: string) => void;
}) {
  const palette = useMemo(() => readPalette(), []);
  const labels = useMemo(() => participantLabels(session), [session]);
  const headlineId = useMemo(() => headlineMetricId(rows), [rows]);
  const summary = useMemo(
    () => (headlineId === null ? null : rankMetric(rows, headlineId)),
    [headlineId, rows],
  );
  const zones = useMemo(() => zoneBreakdown(rows), [rows]);
  const fact = useMemo(
    () => leadingFact(summary, (value, unit) => formatMetricValue(value, unit).text, (entityId) => labels.get(entityId)),
    [labels, summary],
  );

  const selectRanked = (entityId: string) => {
    const entry = summary?.ranked.find((candidate) => candidate.entityId === entityId);
    if (!entry || !summary) return;
    onSelectResult(summary.metricId, entry.derivedMetricId);
    if (entry.subjectId) onSelectSubject(entry.subjectId);
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <ContextStrip session={session} metricTotal={total} fact={fact} onSelectFact={() => {
        if (fact && summary) {
          onSelectResult(summary.metricId, fact.derivedMetricId);
          if (fact.subjectId) onSelectSubject(fact.subjectId);
        }
      }} />

      {summary === null ? (
        <StatePanel
          state="empty"
          title="No derived metric is served for this session."
          detail="Metrics appear after the deterministic processor and Gold rebuild path runs; the stream contracts below are still available."
          className="min-h-48"
        />
      ) : (
        <div className="grid min-h-0 shrink-0 grid-cols-1 gap-px bg-border-subtle xl:grid-cols-2">
          <ChartCard
            title={summary.metricName}
            unit={summary.siUnit}
            measurementClass={summary.measurementClass}
            note={
              summary.ranked.length > MAX_RANKED_ENTITIES
                ? `Top ${MAX_RANKED_ENTITIES} of ${summary.ranked.length} entities`
                : `${summary.ranked.length} entities`
            }
          >
            <EChart
              ariaLabel={`${summary.metricName} ranked by entity`}
              option={rankedMetricOption(summary, palette, (entityId) => labels.get(entityId))}
              onPointClick={(selection) => {
                if (selection.seriesName === null) return;
                const entries = [...summary.ranked.slice(0, MAX_RANKED_ENTITIES)].reverse();
                const entry = entries[selection.dataIndex];
                if (entry) selectRanked(entry.entityId);
              }}
            />
          </ChartCard>

          {zones ? (
            <ChartCard
              title={zones.label}
              unit={zones.siUnit}
              measurementClass={zones.measurementClass}
              note={`${zones.zones.join(" · ")} thresholds are processor parameters`}
            >
              <EChart
                ariaLabel="Distance by speed zone for each entity"
                option={zoneBreakdownOption(zones, palette, undefined, (entityId) => labels.get(entityId))}
              />
            </ChartCard>
          ) : (
            <StreamContracts
              session={session}
              streamFilter={streamFilter}
              onSelectStream={onSelectStream}
            />
          )}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-border-subtle xl:grid-cols-2">
        {zones ? (
          <StreamContracts
            session={session}
            streamFilter={streamFilter}
            onSelectStream={onSelectStream}
          />
        ) : null}
        <MetricTable
          labels={labels}
          rows={rows}
          total={total}
          selectedResult={selectedResult}
          onSelectResult={onSelectResult}
          onSelectSubject={onSelectSubject}
          className={zones ? undefined : "xl:col-span-2"}
        />
      </div>
    </div>
  );
}

/** Session identity and scale, plus one attributable served value. */
function ContextStrip({
  session,
  metricTotal,
  fact,
  onSelectFact,
}: {
  session: SessionDetail;
  metricTotal: number;
  fact: ReturnType<typeof leadingFact>;
  onSelectFact: () => void;
}) {
  const modalities = [...new Set(session.streams.map((stream) => stream.modality))].sort();
  return (
    <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h2 className="t-surface-title">
            {session.session.label ?? session.session.session_id}
          </h2>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-muted">
            <span className="capitalize">{session.session.kind}</span>
            <span className="text-border-strong">·</span>
            {modalities.map((modality) => (
              <ModalityBadge key={modality} modality={modality} />
            ))}
          </p>
        </div>
        <dl className="flex shrink-0 flex-wrap items-end gap-5">
          <Stat label="Participants" value={session.participants.length} />
          <Stat label="Trials" value={session.trials.length} />
          <Stat label="Streams" value={session.streams.length} />
          <Stat label="Derived metrics" value={metricTotal} />
        </dl>
      </div>
      {fact ? (
        <button
          type="button"
          onClick={onSelectFact}
          className="mt-3 flex w-full items-baseline gap-3 rounded-control border border-border-subtle bg-surface-0 px-3 py-2 text-left transition-colors duration-quick hover:border-border-strong hover:bg-surface-2"
        >
          <span className="t-section max-w-44 shrink-0 text-text-muted">
            {fact.label}
          </span>
          <span className="t-value mono shrink-0 whitespace-nowrap tabular">
            {fact.value}
          </span>
          <span className="mono truncate text-[11px] text-text-muted">{fact.detail}</span>
          <span className="ml-auto shrink-0">
            <MeasurementClassBadge measurementClass={fact.measurementClass} compact />
          </span>
        </button>
      ) : null}
    </header>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-right">
      <dd className="t-value mono tabular">
        {value.toLocaleString("en-US")}
      </dd>
      <dt className="t-section mt-1 text-text-muted">{label}</dt>
    </div>
  );
}

function ChartCard({
  title,
  unit,
  measurementClass,
  note,
  children,
}: {
  title: string;
  unit: string;
  measurementClass: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex min-h-72 min-w-0 flex-col bg-surface-1">
      <header className="flex shrink-0 flex-wrap items-baseline justify-between gap-2 border-b border-border-subtle px-3 py-2">
        <h3 className="t-analysis-title">
          {title}
          {unit !== "1" ? (
            <span className="ml-1.5 text-[11px] font-normal text-text-muted">[{unit}]</span>
          ) : null}
        </h3>
        <span className="flex items-center gap-2 text-[10px] text-text-muted">
          {note}
          <MeasurementClassBadge measurementClass={measurementClass} compact />
        </span>
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}

/** Stream contracts: available, and deliberately subordinate to the analysis. */
function StreamContracts({
  session,
  streamFilter,
  onSelectStream,
}: {
  session: SessionDetail;
  streamFilter: string | null;
  onSelectStream: (streamId: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="flex min-h-0 min-w-0 flex-col bg-surface-1">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex shrink-0 items-center gap-1.5 border-b border-border-subtle px-3 py-2 text-left hover:bg-surface-2"
      >
        {open ? (
          <ChevronDown size={13} aria-hidden="true" className="text-text-muted" />
        ) : (
          <ChevronRight size={13} aria-hidden="true" className="text-text-muted" />
        )}
        <h3 className="t-analysis-title">Stream contracts</h3>
        <span className="text-[11px] text-text-muted">
          {session.streams.length} streams · clock, frame and synchronization
        </span>
      </button>
      {open ? (
        <ul className="min-h-0 flex-1 divide-y divide-border-subtle/60 overflow-y-auto">
          {session.streams.map((stream) => (
            <li key={stream.stream_id}>
              <button
                type="button"
                onClick={() =>
                  onSelectStream(streamFilter === stream.stream_id ? null : stream.stream_id)
                }
                className={cn(
                  "w-full px-3 py-2 text-left transition-colors duration-quick hover:bg-surface-2",
                  streamFilter === stream.stream_id && "bg-surface-3",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <ModalityBadge modality={stream.modality} />
                    <span className="mono truncate text-[12px] text-text-secondary">
                      {stream.stream_id}
                    </span>
                  </span>
                  <MeasurementClassBadge measurementClass={stream.measurement_class} compact />
                </div>
                <div className="mt-1 grid grid-cols-2 gap-x-3 text-[10px] text-text-muted">
                  <span>
                    {stream.nominal_sampling_rate_hz !== null
                      ? `${stream.nominal_sampling_rate_hz} Hz`
                      : "rate unknown"}
                  </span>
                  <span className="mono truncate">sync {stream.synchronization_spec_id}</span>
                  <span className="mono truncate">clock {stream.clock_id}</span>
                  <span className="mono truncate">
                    frame {stream.coordinate_frame_id ?? "unavailable"}
                  </span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-3 py-2 text-[11px] leading-relaxed text-text-muted">
          Synchronization is claimed only where a stream declares an explicit specification;
          streams without one are never force-aligned.
        </p>
      )}
    </section>
  );
}

function metricColumns(labels: ReadonlyMap<string, string>): DataTableColumn<MetricValue>[] {
  return [
  {
    id: "metric",
    header: "Metric",
    size: 2.6,
    accessor: (metric) => metric.metric_name ?? metric.metric_id,
    cell: (metric) => (
      <span className="min-w-0">
        <span
          className="block truncate text-[12px] text-text-secondary"
          title={metric.metric_name ?? metric.metric_id}
        >
          {metric.metric_name ?? metric.metric_id}
        </span>
        <span className="mono block truncate text-[10px] text-text-muted" title={metric.metric_id}>
          {metric.metric_id}
        </span>
      </span>
    ),
  },
  {
    id: "entity",
    header: "Entity",
    size: 1.6,
    accessor: (metric) => {
      const key = entityKeyOf(metric) ?? "";
      return labels.get(key) ?? key;
    },
    cell: (metric) => {
      const key = entityKeyOf(metric);
      const label = key === null ? undefined : labels.get(key);
      return (
        <span className="min-w-0" title={key ?? ""}>
          <span className="block truncate text-[11px] text-text-secondary">{label ?? key ?? "—"}</span>
          {label ? <span className="mono block truncate text-[10px] text-text-muted">{key}</span> : null}
        </span>
      );
    },
  },
  {
    id: "value",
    header: "Value",
    size: 1.3,
    align: "right",
    accessor: (metric) => metric.value_num ?? Number.NEGATIVE_INFINITY,
    cell: (metric) => (
      <span
        className="mono truncate tabular text-[12px] text-text-primary"
        title={
          metric.value_num === null
            ? "unavailable"
            : `Exact value: ${metric.value_num} ${metric.si_unit}`
        }
      >
        {formatMetricValue(metric.value_num, metric.si_unit).text}
      </span>
    ),
  },
  {
    id: "class",
    header: "Class",
    size: 1.5,
    accessor: (metric) => metric.measurement_class,
    cell: (metric) => <MeasurementClassBadge measurementClass={metric.measurement_class} compact />,
  },
  ];
}

function MetricTable({
  labels,
  rows,
  total,
  selectedResult,
  onSelectResult,
  onSelectSubject,
  className,
}: {
  labels: ReadonlyMap<string, string>;
  rows: readonly MetricValue[];
  total: number;
  selectedResult: string | null;
  onSelectResult: (metricId: string, derivedMetricId: string) => void;
  onSelectSubject: (subjectId: string) => void;
  className?: string | undefined;
}) {
  const [filter, setFilter] = useState("");
  const columns = useMemo(() => metricColumns(labels), [labels]);
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? rows.filter((row) =>
        `${row.metric_id} ${row.metric_name ?? ""} ${entityKeyOf(row) ?? ""} ${labels.get(entityKeyOf(row) ?? "") ?? ""}`
          .toLowerCase()
          .includes(needle),
      )
    : rows;

  return (
    <section className={cn("flex min-h-72 min-w-0 flex-col bg-surface-1", className)}>
      <header className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border-subtle px-3 py-2">
        <h3 className="t-analysis-title">Derived metrics</h3>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter by metric or entity"
          aria-label="Filter derived metrics"
          className="h-6 w-56 rounded-control border border-border-subtle bg-surface-0 px-2 text-[11px] outline-none transition-colors duration-quick focus:border-accent"
        />
        <span className="ml-auto text-[10px] tabular text-text-muted">
          {visible.length.toLocaleString("en-US")} of {total.toLocaleString("en-US")}
          {total > rows.length ? " (first page)" : ""}
        </span>
      </header>
      <div className="min-h-0 flex-1">
        <DataTable
          ariaLabel="Derived metrics"
          rows={visible}
          columns={columns}
          rowHeight={38}
          getRowId={(metric) => metric.derived_metric_id}
          selectedRowId={selectedResult}
          onRowClick={(metric) => {
            onSelectResult(metric.metric_id, metric.derived_metric_id);
            if (metric.subject_id) onSelectSubject(metric.subject_id);
          }}
          emptyState={
            <StatePanel state="empty" title="No derived metric matches this filter." />
          }
        />
      </div>
    </section>
  );
}
