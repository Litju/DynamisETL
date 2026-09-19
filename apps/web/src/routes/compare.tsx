import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";

import { MeasurementClassBadge } from "@/components/common/Badges";
import { Panel, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { datasetsQuery, metricsQuery } from "@/lib/api/queries";
import { compareSearchSchema, parseSearch } from "@/lib/search";
import type { CompareSearch } from "@/lib/search";


export function defineCompareRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/compare",
  validateSearch: (search: Record<string, unknown>) => parseSearch(compareSearchSchema, search),
  component: ComparePage,
});
}

/**
 * Compare mode: trial/subject/period comparisons within data that shares an
 * identity boundary. Cross-dataset comparison is semantic only and never fuses
 * subject identity.
 */
export function ComparePage() {
  const search = useSearch({ from: "/compare" });
  const navigate = useNavigate();
  const datasets = useQuery(datasetsQuery());
  const [metricId, setMetricId] = useState(search.metric ?? "pose.angular_rom.left_knee");

  const updateSearch = (patch: Partial<CompareSearch>) => {
    void navigate({
      to: "/compare",
      search: (previous: Record<string, unknown>) => ({ ...previous, ...patch }),
      replace: true,
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border-subtle bg-surface-1 px-3 py-2">
        <label className="flex items-center gap-1 text-[11px] text-text-muted">
          metric
          <input
            value={metricId}
            onChange={(event) => setMetricId(event.target.value)}
            className="mono h-6 w-72 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px]"
            aria-label="Metric to compare"
          />
        </label>
        <button
          type="button"
          onClick={() => updateSearch({ metric: metricId })}
          className="rounded-control border border-border-strong px-2 py-1 text-[12px] hover:bg-surface-2"
        >
          Compare metric
        </button>
        <span className="ml-auto text-[11px] text-text-muted">
          identities are preserved; unrelated datasets are never fused
        </span>
      </div>
      {search.metric ? (
        <ComparePanels metricId={search.metric} />
      ) : (
        <StatePanel
          state="empty"
          title="No comparison configured."
          detail="Enter a metric id to compare its current-revision values across datasets/sessions. Dataset and subject identity boundaries are preserved."
        />
      )}
      {datasets.isError ? (
        <ErrorPanel error={datasets.error} onRetry={() => void datasets.refetch()} />
      ) : null}
    </div>
  );
}

function ComparePanels({ metricId }: { metricId: string }) {
  const query = useQuery(metricsQuery({ metricId, limit: 100 }));
  if (query.isPending) return <LoadingPanel label="Loading comparison values" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data.total === 0) {
    return (
      <StatePanel
        state="empty"
        title="No current value serves this metric id."
        detail="Check the metric id in Methodology, or run the processor and Gold rebuild first."
      />
    );
  }
  return (
    <div className="grid min-h-0 flex-1 grid-cols-2 gap-px overflow-auto bg-border-subtle">
      {[0, 1].map((slot) => (
        <Panel
          key={slot}
          title={slot === 0 ? "Selection A" : "Selection B"}
          className="min-h-64"
        >
          <ul className="divide-y divide-border-subtle/60">
            {query.data.rows
              .filter((_row, index) => index % 2 === slot)
              .map((row) => (
                <li key={row.derived_metric_id} className="px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="mono text-[11px] text-text-secondary">
                      {row.dataset_id} / {row.session_id ?? "—"}
                      {row.subject_id ? ` / ${row.subject_id}` : ""}
                    </span>
                    <MeasurementClassBadge measurementClass={row.measurement_class} compact />
                  </div>
                  <div className="mono mt-1 text-[13px] tabular">
                    {row.value_num !== null ? `${row.value_num} ${row.si_unit}` : "unavailable"}
                  </div>
                  <div className="mono text-[10px] text-text-muted">
                    run {row.run_id} · code {row.code_git_sha?.slice(0, 12) ?? "unknown"}
                  </div>
                </li>
              ))}
          </ul>
          <SectionTitle>Boundary note</SectionTitle>
          <p className="px-3 pb-3 text-[11px] text-text-muted">
            Values from different datasets share semantics only; subject identity is never merged
            and interchangeability is not established.
          </p>
        </Panel>
      ))}
    </div>
  );
}
