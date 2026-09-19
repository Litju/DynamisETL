import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";

import { MeasurementClassBadge } from "@/components/common/Badges";
import { KeyValueRow, Panel, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { methodologyQuery, runsQuery } from "@/lib/api/queries";
import { methodsSearchSchema, parseSearch } from "@/lib/search";
import type { MethodsSearch } from "@/lib/search";


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
  const runs = useQuery(runsQuery({ limit: 100 }));

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
          Inspect
        </button>
        <span className="ml-auto text-[11px] text-text-muted">
          exact algorithm/run lineage, not a project-wide graph
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <Panel title="Processing runs" className="min-h-64">
          {runs.isPending ? <LoadingPanel label="Loading processing runs" /> : null}
          {runs.isError ? (
            <ErrorPanel error={runs.error} onRetry={() => void runs.refetch()} />
          ) : null}
          {runs.isSuccess ? (
            <table className="w-full border-collapse text-[12px]">
              <thead className="sticky top-0 bg-surface-1 text-left text-[11px] uppercase tracking-wider text-text-muted">
                <tr className="border-b border-border-subtle">
                  <th scope="col" className="px-2 py-1 font-medium">
                    Run
                  </th>
                  <th scope="col" className="px-2 py-1 font-medium">
                    Algorithm
                  </th>
                  <th scope="col" className="px-2 py-1 font-medium">
                    Dataset
                  </th>
                  <th scope="col" className="px-2 py-1 font-medium">
                    Code SHA
                  </th>
                  <th scope="col" className="px-2 py-1 text-right font-medium">
                    Metrics
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.data.rows.map((run) => (
                  <tr key={run.run_id} className="border-b border-border-subtle/60">
                    <td className="mono px-2 py-1.5 text-[11px]">{run.run_id}</td>
                    <td className="px-2 py-1.5">
                      <div className="mono text-[11px] text-text-secondary">
                        {run.algorithm_id}@{run.algorithm_version}
                      </div>
                      <div className="text-[10px] text-text-muted">
                        {run.algorithm_name ?? "unregistered name"}
                      </div>
                    </td>
                    <td className="mono px-2 py-1.5 text-[11px] text-text-muted">
                      {run.dataset_id}
                    </td>
                    <td className="mono px-2 py-1.5 text-[11px]">
                      {run.code_git_sha ?? (
                        <span className="text-quality-warning">unknown (development)</span>
                      )}
                    </td>
                    <td className="mono px-2 py-1.5 text-right tabular">{run.metric_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </Panel>
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
      </div>
    </div>
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
