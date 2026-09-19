import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";

import { Panel } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { runsQuery } from "@/lib/api/queries";
import { parseSearch, runsSearchSchema } from "@/lib/search";
import type { RunsSearch } from "@/lib/search";


export function defineRunsRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/runs",
  validateSearch: (search: Record<string, unknown>) => parseSearch(runsSearchSchema, search),
  component: RunsPage,
});
}

export function RunsPage() {
  const search = useSearch({ from: "/runs" });
  const navigate = useNavigate();
  const runs = useQuery(runsQuery({ datasetId: search.dataset, limit: 200 }));

  return (
    <Panel title="Processing runs / provenance">
      <div className="flex items-center gap-2 border-b border-border-subtle p-2">
        <input
          value={search.dataset ?? ""}
          onChange={(event) =>
            void navigate({
              to: "/runs",
              search: (previous: RunsSearch) => ({
                ...previous,
                dataset: event.target.value || undefined,
              }),
              replace: true,
            })
          }
          placeholder="dataset id"
          aria-label="Filter runs by dataset"
          className="mono h-6 w-64 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px]"
        />
        <span className="text-[11px] text-text-muted">
          every served value resolves to one of these runs
        </span>
      </div>
      {runs.isPending ? <LoadingPanel label="Loading processing runs" /> : null}
      {runs.isError ? <ErrorPanel error={runs.error} onRetry={() => void runs.refetch()} /> : null}
      {runs.isSuccess ? (
        runs.data.total === 0 ? (
          <StatePanel state="empty" title="No processing run matches the filter." />
        ) : (
          <table className="w-full border-collapse text-[12px]">
            <thead className="sticky top-0 bg-surface-1 text-left text-[11px] uppercase tracking-wider text-text-muted">
              <tr className="border-b border-border-subtle">
                <th scope="col" className="px-2 py-1 font-medium">
                  Run
                </th>
                <th scope="col" className="px-2 py-1 font-medium">
                  Dataset
                </th>
                <th scope="col" className="px-2 py-1 font-medium">
                  Algorithm
                </th>
                <th scope="col" className="px-2 py-1 font-medium">
                  Parameters SHA
                </th>
                <th scope="col" className="px-2 py-1 font-medium">
                  Input checksums
                </th>
                <th scope="col" className="px-2 py-1 text-right font-medium">
                  Metrics
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.data.rows.map((run) => (
                <tr key={run.run_id} className="border-b border-border-subtle/60">
                  <td className="px-2 py-1.5">
                    <div className="mono text-[11px]">{run.run_id}</div>
                    <div className="mono text-[10px] text-text-muted">
                      {run.started_at ?? "no timestamp"}
                    </div>
                  </td>
                  <td className="mono px-2 py-1.5 text-[11px] text-text-muted">
                    {run.dataset_id}
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="mono text-[11px] text-text-secondary">
                      {run.algorithm_id}@{run.algorithm_version}
                    </div>
                    <div className="mono text-[10px] text-text-muted">
                      code {run.code_git_sha ?? "unknown (development-only)"}
                    </div>
                  </td>
                  <td className="mono px-2 py-1.5 text-[10px] text-text-muted">
                    {run.parameters_hash ?? "—"}
                  </td>
                  <td className="mono px-2 py-1.5 text-[10px] text-text-muted">
                    {run.input_checksums.length > 0
                      ? run.input_checksums.map((checksum) => checksum.slice(0, 10)).join(", ")
                      : "—"}
                  </td>
                  <td className="mono px-2 py-1.5 text-right tabular">{run.metric_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : null}
    </Panel>
  );
}
