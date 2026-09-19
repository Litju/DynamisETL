import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { lazy, Suspense, useState } from "react";

import { MeasurementClassBadge } from "@/components/common/Badges";
import { KeyValueRow, Panel, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { methodologyQuery, provenanceQuery } from "@/lib/api/queries";
import { methodsSearchSchema, parseSearch } from "@/lib/search";
import type { MethodsSearch } from "@/lib/search";

const LineageGraph = lazy(() => import("@/components/lineage/LineageGraph"));


export function defineMethodsRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/methods",
  validateSearch: (search: Record<string, unknown>) => parseSearch(methodsSearchSchema, search),
  component: MethodsPage,
});
}

/**
 * Methodology / provenance surface: metric definitions, algorithm revisions,
 * parameters and code revision per processing run.
 */
export function MethodsPage() {
  const search = useSearch({ from: "/methods" });
  const navigate = useNavigate();
  const [lookup, setLookup] = useState(search.metric ?? "");
  const [resultLookup, setResultLookup] = useState(search.result ?? "");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border-subtle bg-surface-1 px-3 py-2">
        <label className="flex items-center gap-1 text-[11px] text-text-muted">
          metric id
          <input
            value={lookup}
            onChange={(event) => setLookup(event.target.value)}
            placeholder="pose.angular_vel.rms.left_knee"
            className="mono h-6 w-80 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px]"
            aria-label="Metric id"
          />
        </label>
        <button
          type="button"
          onClick={() =>
            void navigate({
              to: "/methods",
              search: (previous: MethodsSearch) => ({
                ...previous,
                metric: lookup || undefined,
              }),
              replace: true,
            })
          }
          className="rounded-control border border-border-strong px-2 py-1 text-[12px] hover:bg-surface-2"
        >
          Inspect metric
        </button>
        <label className="flex items-center gap-1 text-[11px] text-text-muted">
          result id
          <input
            value={resultLookup}
            onChange={(event) => setResultLookup(event.target.value)}
            placeholder="dm-…"
            className="mono h-6 w-56 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px]"
            aria-label="Derived metric id"
          />
        </label>
        <button
          type="button"
          onClick={() =>
            void navigate({
              to: "/methods",
              search: (previous: MethodsSearch) => ({
                ...previous,
                result: resultLookup || undefined,
              }),
              replace: true,
            })
          }
          className="rounded-control border border-border-strong px-2 py-1 text-[12px] hover:bg-surface-2"
        >
          Open lineage
        </button>
        <span className="ml-auto text-[11px] text-text-muted">
          exact algorithm/run lineage, not a project-wide graph
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        
        {search.metric ? (
          <Panel title="Selected metric methodology" className="min-h-48">
            <MetricDefinitionAsync metricId={search.metric} />
          </Panel>
        ) : (
          <StatePanel
            state="empty"
            title="No metric selected."
            detail="Inspect a metric id to read its definition, measurement class, parameters hash and exact code revision. The laboratory inspector follows a served result instead."
          />
        )}
        {search.result ? (
          <Panel title="Selected result lineage" className="min-h-96">
            <SelectedLineage derivedMetricId={search.result} />
          </Panel>
        ) : null}
      </div>
    </div>
  );
}

function SelectedLineage({ derivedMetricId }: { derivedMetricId: string }) {
  const query = useQuery(provenanceQuery(derivedMetricId));
  if (query.isPending) return <LoadingPanel label="Loading selected lineage" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <Suspense fallback={<LoadingPanel label="Loading lineage renderer" />}>
      <LineageGraph graph={query.data} />
    </Suspense>
  );
}

function MetricDefinitionAsync({ metricId }: { metricId: string }) {
  const query = useQuery(methodologyQuery(metricId));
  if (query.isPending) return <LoadingPanel label="Loading metric definition" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  const data = query.data;
  return (
    <div className="p-3">
      <dl>
        <KeyValueRow label="name">{data.metric.name}</KeyValueRow>
        <KeyValueRow label="SI unit" mono>
          {data.metric.si_unit}
        </KeyValueRow>
        <KeyValueRow label="class">
          <MeasurementClassBadge measurementClass={data.metric.measurement_class} />
        </KeyValueRow>
        <KeyValueRow label="definition">{data.metric.description ?? "—"}</KeyValueRow>
        <KeyValueRow label="algorithm" mono>
          {data.algorithm ? `${data.algorithm.algorithm_id}@${data.algorithm.version}` : "—"}
        </KeyValueRow>
        <KeyValueRow label="code sha" mono>
          {data.algorithm?.code_git_sha ?? "unknown"}
        </KeyValueRow>
      </dl>
      <SectionTitle>Reference fields</SectionTitle>
      <ul className="list-disc pl-4 text-[12px] text-text-muted">
        {data.provenance_fields.map((field) => (
          <li key={field}>{field}</li>
        ))}
      </ul>
    </div>
  );
}
