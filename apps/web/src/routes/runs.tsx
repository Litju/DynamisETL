import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";

import { Panel } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { runsQuery } from "@/lib/api/queries";
import { parseSearch, runsSearchSchema } from "@/lib/search";
import type { RunsSearch } from "@/lib/search";
import type { RunPage } from "@/api/types";

export function defineRunsRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/runs",
    validateSearch: (search: Record<string, unknown>) => parseSearch(runsSearchSchema, search),
    component: RunsPage,
  });
}

type RunRow = RunPage["rows"][number];

const RUN_COLUMNS: DataTableColumn<RunRow>[] = [
  {
    id: "run",
    header: "Run",
    size: 1.6,
    accessor: (run) => run.run_id,
    cell: (run) => (
      <span className="min-w-0">
        <span className="mono block truncate text-[11px] text-text-secondary">{run.run_id}</span>
        <span className="mono block truncate text-[10px] text-text-muted">
          {run.started_at ?? "no timestamp"}
        </span>
      </span>
    ),
  },
  {
    id: "dataset",
    header: "Dataset",
    size: 1.3,
    accessor: (run) => run.dataset_id,
    cell: (run) => <span className="mono text-[11px]">{run.dataset_id}</span>,
  },
  {
    id: "algorithm",
    header: "Algorithm",
    size: 2,
    accessor: (run) => `${run.algorithm_id}@${run.algorithm_version ?? "?"}`,
    cell: (run) => (
      <span className="min-w-0">
        <span className="mono block truncate text-[11px] text-text-secondary">
          {run.algorithm_id}@{run.algorithm_version}
        </span>
        <span className="block truncate text-[10px] text-text-muted">
          {run.algorithm_name ?? "unregistered name"}
        </span>
      </span>
    ),
  },
  {
    id: "code",
    header: "Code SHA",
    size: 1.4,
    accessor: (run) => run.code_git_sha ?? "",
    cell: (run) =>
      run.code_git_sha ? (
        <span className="mono truncate text-[11px]">{run.code_git_sha}</span>
      ) : (
        <span className="text-[11px] text-quality-warning">unknown (development-only)</span>
      ),
  },
  {
    id: "parameters",
    header: "Parameters SHA",
    size: 1.4,
    accessor: (run) => run.parameters_hash ?? "",
    cell: (run) => (
      <span className="mono truncate text-[10px] text-text-muted">{run.parameters_hash ?? "—"}</span>
    ),
  },
  {
    id: "metrics",
    header: "Metrics",
    size: 0.7,
    align: "right",
    accessor: (run) => run.metric_count,
  },
];

export function RunsPage() {
  const search = useSearch({ from: "/runs" });
  const navigate = useNavigate();
  const runs = useQuery(runsQuery({ datasetId: search.dataset, limit: 200 }));

  return (
    <Panel title="Processing runs / provenance" bodyClassName="overflow-hidden">
      <div className="flex h-full min-h-0 flex-col">
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
        <div className="min-h-0 flex-1">
          {runs.isPending ? <LoadingPanel label="Loading processing runs" /> : null}
          {runs.isError ? (
            <ErrorPanel error={runs.error} onRetry={() => void runs.refetch()} />
          ) : null}
          {runs.isSuccess ? (
            <DataTable
              ariaLabel="Processing runs"
              rows={runs.data.rows}
              columns={RUN_COLUMNS}
              getRowId={(run) => run.run_id}
              emptyState={<StatePanel state="empty" title="No processing run matches the filter." />}
            />
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
