import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";

import { CopyableId } from "@/components/common/CopyableId";
import { EChart } from "@/components/charts/EChart";
import { rankedMetricOption } from "@/components/charts/overview-options";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { runsQuery, servingStatusQuery } from "@/lib/api/queries";
import { readPalette } from "@/lib/chart-palette";
import { cn } from "@/lib/cn";
import { QUALITY_STATES } from "@/lib/measurement";
import { parseSearch, runsSearchSchema } from "@/lib/search";
import type { RunsSearch } from "@/lib/search";
import type { RunPage } from "@/api/types";

type RunRow = RunPage["rows"][number];

const RUN_PAGE_LIMIT = 500;

export function defineRunsRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/runs",
    validateSearch: (search: Record<string, unknown>) => parseSearch(runsSearchSchema, search),
    component: RunsPage,
  });
}

/**
 * Processing runs.
 *
 * Every served value resolves to one of these runs, so the surface has to
 * communicate reproducibility rather than list log rows: which processor
 * produced how much, against which code revision, and what a selected run
 * consumed and emitted.
 */
export function RunsPage() {
  const search = useSearch({ from: "/runs" });
  const navigate = useNavigate();
  const runs = useQuery(runsQuery({ datasetId: search.dataset, limit: RUN_PAGE_LIMIT }));
  const status = useQuery(servingStatusQuery());
  const palette = useMemo(() => readPalette(), []);

  const update = (patch: Partial<RunsSearch>) => {
    void navigate({
      to: "/runs",
      search: (previous: RunsSearch) => ({ ...previous, ...patch }),
      replace: true,
    });
  };

  const rows = useMemo(() => runs.data?.rows ?? [], [runs.data]);
  const selected = rows.find((run) => run.run_id === search.run) ?? null;
  const summary = useMemo(() => summariseRuns(rows), [rows]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-3">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="min-w-0">
            <h1 className="t-surface-title">
              Processing runs
            </h1>
            <p className="mt-0.5 max-w-2xl text-[12px] text-text-secondary">
              Every served value resolves to one of these runs, and through it to an exact code
              revision, parameter set and set of input checksums.
            </p>
          </div>
          <dl className="flex shrink-0 flex-wrap items-end gap-5">
            <Stat label="Runs" value={status.data?.run_count ?? rows.length} />
            <Stat label="Processors" value={summary.processors} />
            <Stat
              label="Unknown code revision"
              value={summary.unknownSha}
              tone={summary.unknownSha > 0 ? "warning" : "valid"}
            />
          </dl>
        </div>
      </header>

      <div className="flex shrink-0 items-center gap-2 border-b border-border-subtle bg-surface-1 px-4 py-2">
        <input
          value={search.dataset ?? ""}
          onChange={(event) => update({ dataset: event.target.value || undefined })}
          placeholder="Filter by dataset"
          aria-label="Filter runs by dataset"
          className="mono h-7 w-56 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px] outline-none transition-colors duration-quick focus:border-accent"
        />
        <span className="ml-auto text-[11px] tabular text-text-muted">
          {runs.isSuccess
            ? `${rows.length.toLocaleString("en-US")} of ${runs.data.total.toLocaleString("en-US")} runs`
            : ""}
        </span>
      </div>

      {runs.isPending ? <LoadingPanel label="Loading processing runs" /> : null}
      {runs.isError ? <ErrorPanel error={runs.error} onRetry={() => void runs.refetch()} /> : null}
      {runs.isSuccess ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-border-subtle xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <section className="flex min-h-64 min-w-0 flex-col bg-surface-1">
            <div className="min-h-0 flex-1">
              <DataTable
                ariaLabel="Processing runs"
                rows={rows}
                columns={RUN_COLUMNS}
                rowHeight={40}
                getRowId={(run) => run.run_id}
                selectedRowId={search.run ?? null}
                onRowClick={(run) =>
                  update({ run: run.run_id === search.run ? undefined : run.run_id })
                }
                emptyState={
                  <StatePanel state="empty" title="No processing run matches the filter." />
                }
              />
            </div>
          </section>

          <section className="flex min-h-64 min-w-0 flex-col bg-surface-1">
            {selected ? (
              <RunDetail run={selected} />
            ) : (
              <>
                <header className="shrink-0 border-b border-border-subtle px-4 py-2">
                  <h2 className="t-analysis-title">
                    Runs by processor
                  </h2>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    Runs in view per processor revision. Tactical processors emit series artifacts rather than scalar metrics. Select a run to see its exact inputs, revision and outputs.
                  </p>
                </header>
                <div className="min-h-0 flex-1">
                  {summary.byProcessor.ranked.length > 0 ? (
                    <EChart
                      ariaLabel="Processing runs per processor revision"
                      option={rankedMetricOption(summary.byProcessor, palette)}
                    />
                  ) : (
                    <StatePanel state="empty" title="No processing run is registered yet." />
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}

interface RunsSummary {
  readonly processors: number;
  readonly unknownSha: number;
  readonly byProcessor: Parameters<typeof rankedMetricOption>[0];
}

/**
 * Counts over the loaded runs.
 *
 * These describe the page in view, not the whole history: the header states
 * the served total separately so a filtered page never reads as the archive.
 */
export function summariseRuns(rows: readonly RunRow[]): RunsSummary {
  const perProcessor = new Map<string, { metrics: number; runId: string }>();
  let unknownSha = 0;
  for (const run of rows) {
    if (run.code_git_sha === null) unknownSha += 1;
    const key = `${run.algorithm_name ?? run.algorithm_id}@${run.algorithm_version ?? "?"}`;
    const entry = perProcessor.get(key) ?? { metrics: 0, runId: run.run_id };
    entry.metrics += 1;
    perProcessor.set(key, entry);
  }
  return {
    processors: perProcessor.size,
    unknownSha,
    byProcessor: {
      metricId: "runs.runs_by_processor",
      metricName: "Processing runs",
      siUnit: "1",
      measurementClass: "PIPELINE_DERIVED",
      ranked: [...perProcessor.entries()]
        .map(([entityId, entry]) => ({
          entityId,
          value: entry.metrics,
          derivedMetricId: entry.runId,
          subjectId: null,
        }))
        .sort((left, right) =>
          right.value !== left.value
            ? right.value - left.value
            : left.entityId < right.entityId
              ? -1
              : 1,
        ),
    },
  };
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "valid" | "warning";
}) {
  return (
    <div className="text-right">
      <dd
        className={cn(
          "t-value mono tabular",
          tone === "warning"
            ? "text-quality-warning"
            : tone === "valid"
              ? "text-quality-valid"
              : "text-text-primary",
        )}
      >
        {value.toLocaleString("en-US")}
      </dd>
      <dt className="t-section mt-1 text-text-muted">{label}</dt>
    </div>
  );
}

const RUN_COLUMNS: DataTableColumn<RunRow>[] = [
  {
    id: "processor",
    header: "Processor",
    size: 2.6,
    accessor: (run) => run.algorithm_name ?? run.algorithm_id,
    cell: (run) => (
      <span className="min-w-0">
        <span
          className="block truncate text-[12px] text-text-primary"
          title={run.algorithm_name ?? run.algorithm_id}
        >
          {run.algorithm_name ?? run.algorithm_id}
        </span>
        <span className="mono block truncate text-[10px] text-text-muted" title={run.algorithm_id}>
          {run.algorithm_id}@{run.algorithm_version}
        </span>
      </span>
    ),
  },
  {
    id: "dataset",
    header: "Dataset",
    size: 1.5,
    accessor: (run) => run.dataset_id,
    cell: (run) => (
      <span className="mono truncate text-[11px] text-text-secondary" title={run.dataset_id}>
        {run.dataset_id}
      </span>
    ),
  },
  {
    id: "status",
    header: "Status",
    size: 1,
    accessor: (run) => run.status,
    cell: (run) => <RunStatus status={run.status} />,
  },
  {
    id: "revision",
    header: "Code revision",
    size: 1.2,
    accessor: (run) => run.code_git_sha ?? "",
    cell: (run) =>
      run.code_git_sha ? (
        <span className="mono truncate text-[11px] text-text-muted" title={run.code_git_sha}>
          {run.code_git_sha.slice(0, 10)}
        </span>
      ) : (
        <span className="text-[11px] text-quality-warning">▲ unknown</span>
      ),
  },
  {
    id: "metrics",
    header: "Outputs",
    size: 1.2,
    align: "right",
    accessor: (run) => run.metric_count + run.artifact_count,
    cell: (run) => (
      <span
        className="mono whitespace-nowrap text-[11px] tabular"
        title={`${run.metric_count} derived metrics · ${run.artifact_count} series artifacts`}
      >
        {run.metric_count > 0
          ? `${run.metric_count.toLocaleString("en-US")} metrics`
          : `${run.artifact_count.toLocaleString("en-US")} series`}
      </span>
    ),
  },
  {
    id: "started",
    header: "Started",
    size: 1.4,
    accessor: (run) => run.started_at ?? "",
    cell: (run) => (
      <span className="mono truncate text-[10px] text-text-muted" title={run.started_at ?? ""}>
        {run.started_at?.replace("T", " ").slice(0, 19) ?? "no timestamp"}
      </span>
    ),
  },
];

function RunStatus({ status }: { status: string }) {
  const descriptor =
    status === "completed"
      ? QUALITY_STATES.valid
      : status === "failed"
        ? QUALITY_STATES.quarantined
        : QUALITY_STATES.warning;
  return (
    <span className="flex items-center gap-1 text-[11px]" style={{ color: descriptor.token }}>
      <span aria-hidden="true">{descriptor.glyph}</span>
      {status}
    </span>
  );
}

/** Everything needed to reproduce one run, and what it emitted. */
function RunDetail({ run }: { run: RunRow }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-border-subtle px-4 py-2">
        <h2 className="t-analysis-title truncate">
          {run.algorithm_name ?? run.algorithm_id}
        </h2>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <RunStatus status={run.status} />
          <span className="mono text-[11px] text-text-muted">
            v{run.algorithm_version} · {run.kind ?? "unclassified"}
          </span>
        </div>
        <CopyableId value={run.run_id} label="run id" className="mt-1" />
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <Section title="Reproducibility">
          <dl className="space-y-1.5">
            <EvidenceRow label="Code revision" value={run.code_git_sha} />
            <EvidenceRow label="Parameters hash" value={run.parameters_hash} />
            <TextRow label="Algorithm" value={`${run.algorithm_id}@${run.algorithm_version}`} mono />
          </dl>
        </Section>

        <Section title="Window">
          <dl className="space-y-1.5">
            <TextRow label="Started" value={run.started_at ?? "no timestamp"} mono />
            <TextRow label="Completed" value={run.completed_at ?? "not recorded"} mono />
            <TextRow label="Dataset" value={run.dataset_id} mono />
          </dl>
        </Section>

        <Section title="Outputs">
          <dl className="space-y-1.5">
            <TextRow label="Derived metrics" value={run.metric_count.toLocaleString("en-US")} />
            <TextRow label="Artifacts" value={run.artifact_count.toLocaleString("en-US")} />
          </dl>
          <Link
            to="/compare"
            className="mt-2 inline-block text-[11px] text-accent hover:underline"
          >
            Compare metrics this processor produced →
          </Link>
        </Section>

        <Section title={`Input checksums (${run.input_checksums.length})`}>
          {run.input_checksums.length === 0 ? (
            <p className="text-[11px] text-quality-warning">
              ▲ No input checksum is recorded for this run.
            </p>
          ) : (
            <ul className="space-y-1">
              {run.input_checksums.map((checksum) => (
                <li key={checksum}>
                  <CopyableId value={checksum} label="input checksum" />
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[10px] leading-relaxed text-text-muted">
            A derived value cannot exist without its inputs: the control plane rejects a run whose
            input checksum list is empty.
          </p>
        </Section>

        {run.notes ? (
          <Section title="Notes">
            <p className="text-[11px] leading-relaxed text-text-secondary">{run.notes}</p>
          </Section>
        ) : null}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-4 last:mb-0">
      <h3 className="t-section mb-2 text-text-muted">
        {title}
      </h3>
      {children}
    </section>
  );
}

function TextRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[8rem_minmax(0,1fr)] items-baseline gap-2">
      <dt className="text-[11px] text-text-muted">{label}</dt>
      <dd className={cn("min-w-0 truncate text-[12px] text-text-secondary", mono && "mono")} title={value}>
        {value}
      </dd>
    </div>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="grid grid-cols-[8rem_minmax(0,1fr)] items-baseline gap-2">
      <dt className="text-[11px] text-text-muted">{label}</dt>
      <dd className="min-w-0">
        {value ? (
          <CopyableId value={value} label={label.toLowerCase()} />
        ) : (
          <span className="text-[11px] text-quality-warning">
            ▲ unknown (development-only state)
          </span>
        )}
      </dd>
    </div>
  );
}
