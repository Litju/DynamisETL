import { useQuery } from "@tanstack/react-query";
import {
  createRoute,
  type AnyRoute,
  useNavigate,
  useParams,
  useSearch,
} from "@tanstack/react-router";
import { useCallback, useEffect, useMemo } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { SignalLaboratory } from "@/components/lab/SignalLaboratory";
import { PitchReplay } from "@/components/pitch/PitchReplay";
import { lazy, Suspense } from "react";

const PoseViewer = lazy(() => import("@/components/pose/PoseViewer"));
import type { MetricValue } from "@/api/types";
import { KeyValueRow, Panel, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { metricsQuery, sessionQuery } from "@/lib/api/queries";
import { patchChangesSearch, resolveLabDefaults } from "@/lib/defaults";
import { sessionSurfaces } from "@/lib/capabilities";
import { cn } from "@/lib/cn";
import { formatMetricValue } from "@/lib/measurement";
import { labSearchSchema, parseSearch, WORKBENCH_VIEWS } from "@/lib/search";
import type { LabSearch, WorkbenchView } from "@/lib/search";
import { useAnalysisStore } from "@/lib/state/analysis";
import { tryParseNs } from "@/lib/time";


export function defineLabRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/lab/$datasetId/$sessionId",
  validateSearch: (search: Record<string, unknown>) => parseSearch(labSearchSchema, search),
  component: LabPage,
});
}

export function LabPage() {
  const { datasetId, sessionId } = useParams({ from: "/lab/$datasetId/$sessionId" });
  const search = useSearch({ from: "/lab/$datasetId/$sessionId" });
  const navigate = useNavigate();
  const hydrate = useAnalysisStore((state) => state.hydrate);
  const setNominalRate = useAnalysisStore((state) => state.setNominalRate);
  const session = useQuery(sessionQuery(datasetId, sessionId));

  const durableTimeNs = tryParseNs(search.t_ns);
  const durableSubject = search.subject ?? null;
  const durableView = search.view ?? "overview";
  useEffect(() => {
    hydrate({
      committedTimeNs: durableTimeNs,
      selectedEntityId: durableSubject,
      focusedPanel: durableView,
    });
    return () => {
      useAnalysisStore.getState().resetTransient();
    };
  }, [hydrate, durableSubject, durableTimeNs, durableView]);

  const selectedStream = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((stream) => stream.stream_id === search.stream) ?? null;
  }, [search.stream, session.data]);
  useEffect(() => {
    setNominalRate(selectedStream?.nominal_sampling_rate_hz ?? null);
    return () => setNominalRate(null);
  }, [selectedStream, setNominalRate]);

  const updateSearch = useCallback(
    (patch: Partial<LabSearch>) => {
      void navigate({
        to: "/lab/$datasetId/$sessionId",
        params: { datasetId, sessionId },
        search: (previous: LabSearch) => ({ ...previous, ...patch }),
        replace: true,
      });
    },
    [datasetId, navigate, sessionId],
  );

  // Deterministic real-data defaults. Only keys the URL leaves open are filled,
  // so an explicit deep link and back/forward navigation keep exactly the state
  // they encoded; `replace` keeps the resolution out of the history stack.
  const detail = session.data;
  useEffect(() => {
    if (!detail) return;
    const { patch } = resolveLabDefaults(detail, search);
    if (!patchChangesSearch(patch, search)) return;
    updateSearch(patch);
  }, [detail, search, updateSearch]);

  if (session.isPending) return <LoadingPanel label="Loading laboratory session" />;
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }

  const view: WorkbenchView = search.view ?? "overview";
  // A laboratory tab is offered only when this session has a stream that can
  // open it, so the workbench never advertises an analysis the data cannot
  // render. Provenance follows the selected result and is always reachable.
  const surfaces = sessionSurfaces(session.data.streams);
  const availableViews: WorkbenchView[] = [
    "overview",
    ...WORKBENCH_VIEWS.filter(
      (candidate): candidate is WorkbenchView =>
        candidate !== "overview" &&
        (candidate === "provenance" || surfaces.includes(candidate as never)),
    ),
  ];
  return (
    <div className="flex h-full min-h-0 flex-col">
        <div
          role="tablist"
          aria-label="Laboratory views"
          className="flex h-9 shrink-0 items-center gap-0.5 border-b border-border-subtle bg-surface-1 px-2"
        >
          {availableViews.map((candidate) => (
            <button
              key={candidate}
              type="button"
              role="tab"
              aria-selected={view === candidate}
              onClick={() => updateSearch({ view: candidate })}
              className={cn(
                "relative rounded-control px-2.5 py-1 text-[12px] capitalize transition-colors duration-quick",
                view === candidate
                  ? "bg-surface-3 font-medium text-text-primary"
                  : "text-text-muted hover:bg-surface-2 hover:text-text-secondary",
              )}
            >
              {candidate}
              {view === candidate ? (
                <span
                  aria-hidden="true"
                  className="absolute inset-x-2 -bottom-[5px] h-0.5 rounded-full bg-accent"
                />
              ) : null}
            </button>
          ))}
          <span className="ml-auto flex items-center gap-2 text-[11px] text-text-muted">
            {search.trial ? (
              <span title={`Selected trial ${search.trial}`}>
                Trial <span className="mono text-text-secondary">{search.trial}</span>
              </span>
            ) : null}
            {search.subject ? (
              <span title={`Selected subject ${search.subject}`}>
                Subject <span className="mono text-text-secondary">{search.subject}</span>
              </span>
            ) : null}
          </span>
        </div>
        <div className="min-h-0 flex-1">
          {view === "overview" ? (
            <LabOverview
              datasetId={datasetId}
              sessionId={sessionId}
              streamFilter={search.stream ?? null}
              onSelectStream={(streamId) => updateSearch({ stream: streamId ?? undefined })}
              onSelectResult={(metricId, derivedMetricId) =>
                updateSearch({ metric: metricId, result: derivedMetricId })
              }
              onSelectSubject={(subjectId) => updateSearch({ subject: subjectId })}
            />
          ) : view === "signals" ? (
            <SignalLaboratory />
          ) : view === "field" ? (
            <PitchReplay />
          ) : view === "pose" ? (
            <Suspense fallback={<LoadingPanel label="Loading 3D laboratory" />}>
              <PoseViewer />
            </Suspense>
          ) : (
            <StatePanel
              state="empty"
              title={`${view} view`}
              detail={
                selectedStream
                  ? `Preparing ${selectedStream.modality} stream ${selectedStream.stream_id}.`
                  : "Select a stream in the explorer or overview to populate this view."
              }
            />
          )}
        </div>
      </div>
  );
}

function LabOverview({
  datasetId,
  sessionId,
  streamFilter,
  onSelectStream,
  onSelectResult,
  onSelectSubject,
}: {
  datasetId: string;
  sessionId: string;
  streamFilter: string | null;
  onSelectStream: (streamId: string | null) => void;
  onSelectResult: (metricId: string, derivedMetricId: string) => void;
  onSelectSubject: (subjectId: string) => void;
}) {
  const session = useQuery(sessionQuery(datasetId, sessionId));
  const metrics = useQuery(
    metricsQuery({ datasetId, sessionId, limit: 250 }),
  );
  if (session.isPending || metrics.isPending) {
    return <LoadingPanel label="Loading session context" />;
  }
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }
  const { participants, streams, trials } = session.data;
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-px overflow-auto bg-border-subtle xl:grid-cols-3">
      <Panel title="What am I looking at?" className="min-h-64">
        <dl className="p-1">
          <KeyValueRow label="dataset" mono>
            {datasetId}
          </KeyValueRow>
          <KeyValueRow label="session" mono>
            {sessionId}
          </KeyValueRow>
          <KeyValueRow label="kind">{session.data.session.kind}</KeyValueRow>
          <KeyValueRow label="trials">{trials.length}</KeyValueRow>
          <KeyValueRow label="streams">{streams.length}</KeyValueRow>
          <KeyValueRow label="participants">{participants.length}</KeyValueRow>
        </dl>
        <SectionTitle>Participants</SectionTitle>
        <ul className="flex flex-wrap gap-1 px-3 pb-3">
          {participants.slice(0, 40).map((participant) => (
            <li key={participant.subject_id}>
              <button
                type="button"
                onClick={() => onSelectSubject(participant.subject_id)}
                className="mono rounded-control border border-border-subtle px-1.5 py-0.5 text-[11px] hover:border-accent hover:text-accent"
              >
                {participant.subject_id}
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Modalities, synchronization and quality context" className="min-h-64">
        <ul className="divide-y divide-border-subtle/60">
          {streams.map((stream) => (
            <li key={stream.stream_id}>
              <button
                type="button"
                onClick={() =>
                  onSelectStream(streamFilter === stream.stream_id ? null : stream.stream_id)
                }
                className={cn(
                  "w-full px-3 py-2 text-left hover:bg-surface-2",
                  streamFilter === stream.stream_id && "bg-surface-3",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <ModalityBadge modality={stream.modality} />
                    <span className="mono text-[12px]">{stream.stream_id}</span>
                  </span>
                  <MeasurementClassBadge measurementClass={stream.measurement_class} compact />
                </div>
                <div className="mt-1 grid grid-cols-2 gap-x-3 text-[11px] text-text-muted">
                  <span>
                    {stream.nominal_sampling_rate_hz !== null
                      ? `${stream.nominal_sampling_rate_hz} Hz`
                      : "unknown rate"}
                  </span>
                  <span className="mono truncate">sync {stream.synchronization_spec_id}</span>
                  <span className="mono truncate">clock {stream.clock_id}</span>
                  <span className="mono truncate">
                    frame {stream.coordinate_frame_id ?? "unavailable"}
                  </span>
                  {stream.skeleton_id ? (
                    <span className="mono truncate">skeleton {stream.skeleton_id}</span>
                  ) : null}
                </div>
              </button>
            </li>
          ))}
        </ul>
        <p className="px-3 py-2 text-[11px] text-text-muted">
          Synchronization is only claimed where the stream declares an explicit specification;
          streams without one are never force-aligned.
        </p>
      </Panel>

      <Panel title="Derived metrics" className="min-h-64" bodyClassName="overflow-hidden">
        {metrics.isError ? (
          <ErrorPanel error={metrics.error} onRetry={() => void metrics.refetch()} />
        ) : metrics.data.total === 0 ? (
          <StatePanel
            state="empty"
            title="No derived metric has been computed for this session."
            detail="Metrics appear after the deterministic processor and Gold rebuild path runs."
          />
        ) : (
          <DataTable
            ariaLabel="Derived metrics"
            rows={metrics.data.rows}
            columns={METRIC_COLUMNS}
            getRowId={(metric) => metric.derived_metric_id}
            onRowClick={(metric) => {
              onSelectResult(metric.metric_id, metric.derived_metric_id);
              if (metric.subject_id) onSelectSubject(metric.subject_id);
            }}
            emptyState={<StatePanel state="empty" title="No derived metric in this scope." />}
          />
        )}
      </Panel>
    </div>
  );
}

const METRIC_COLUMNS: DataTableColumn<MetricValue>[] = [
  {
    id: "metric",
    header: "Metric",
    size: 2.4,
    accessor: (metric) => metric.metric_id,
    cell: (metric) => (
      <span className="min-w-0">
        <span className="mono block truncate text-[11px] text-text-secondary">
          {metric.metric_id}
        </span>
        <span className="block truncate text-[10px] text-text-muted">
          {metric.metric_name ?? "definition unavailable"}
        </span>
      </span>
    ),
  },
  {
    id: "entity",
    header: "Entity",
    size: 1,
    accessor: (metric) => metric.entity_id ?? metric.subject_id ?? "",
    cell: (metric) => (
      <span className="mono text-[11px] text-text-muted">
        {metric.entity_id ?? metric.subject_id ?? "—"}
      </span>
    ),
  },
  {
    id: "value",
    header: "Value",
    size: 1.2,
    align: "right",
    accessor: (metric) => metric.value_num ?? Number.NaN,
    cell: (metric) => (
      <span className="mono tabular">
        {formatMetricValue(metric.value_num, metric.si_unit).text}
      </span>
    ),
  },
  {
    id: "class",
    header: "Class",
    size: 1.2,
    accessor: (metric) => metric.measurement_class,
    cell: (metric) => (
      <MeasurementClassBadge measurementClass={metric.measurement_class} compact />
    ),
  },
];
