import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, Link, useNavigate, useSearch } from "@tanstack/react-router";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { KeyValueRow, Panel, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { datasetQuery, datasetsQuery, sessionsQuery } from "@/lib/api/queries";
import type { DatasetSummary } from "@/api/types";
import { catalogSearchSchema, MODALITIES, parseSearch } from "@/lib/search";
import type { CatalogSearch } from "@/lib/search";


export function defineCatalogRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/catalog",
  validateSearch: (search: Record<string, unknown>) => parseSearch(catalogSearchSchema, search),
  component: CatalogPage,
});
}

function filterDatasets(
  datasets: readonly DatasetSummary[],
  search: CatalogSearch,
): DatasetSummary[] {
  const query = search.q?.toLowerCase() ?? "";
  return datasets.filter((dataset) => {
    if (query) {
      const haystack = `${dataset.dataset_id} ${dataset.name} ${dataset.provider}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    if (search.modality && !dataset.modalities.includes(search.modality)) return false;
    return true;
  });
}

export function CatalogPage() {
  const search = useSearch({ from: "/catalog" });
  const navigate = useNavigate();
  const datasets = useQuery(datasetsQuery());

  const updateSearch = (patch: Partial<CatalogSearch>) => {
    void navigate({
      to: "/catalog",
      search: (previous: CatalogSearch) => ({ ...previous, ...patch }),
      replace: true,
    });
  };

  return (
    <div className="flex h-full min-h-0">
      <Panel title="Dataset catalog" className="min-w-0 flex-[3] border-r border-border-subtle">
        <div className="flex items-center gap-2 border-b border-border-subtle p-2">
          <input
            value={search.q ?? ""}
            onChange={(event) => updateSearch({ q: event.target.value || undefined })}
            placeholder="Filter datasets, providers"
            aria-label="Filter datasets"
            className="h-6 w-64 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px] outline-none focus:border-accent"
          />
          <label className="flex items-center gap-1 text-[11px] text-text-muted">
            modality
            <select
              aria-label="Filter by modality"
              value={search.modality ?? ""}
              onChange={(event) =>
                updateSearch({
                  modality: (event.target.value || undefined) as CatalogSearch["modality"],
                })
              }
              className="mono rounded-control border border-border-subtle bg-surface-0 px-1 py-0.5 text-[11px]"
            >
              <option value="">all</option>
              {MODALITIES.map((modality) => (
                <option key={modality} value={modality}>
                  {modality}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1 text-[11px] text-text-muted">
            rights
            <select
              aria-label="Filter by rights"
              value={search.rights ?? "all"}
              onChange={(event) =>
                updateSearch({ rights: event.target.value as CatalogSearch["rights"] })
              }
              className="mono rounded-control border border-border-subtle bg-surface-0 px-1 py-0.5 text-[11px]"
            >
              <option value="all">all</option>
              <option value="commercial">non-commercial only</option>
              <option value="noncommercial">commercial ok</option>
            </select>
          </label>
          <span className="ml-auto text-[11px] text-text-muted">
            {datasets.isSuccess ? `${datasets.data.length} registered` : ""}
          </span>
        </div>

        {datasets.isPending ? <LoadingPanel label="Loading dataset catalog" /> : null}
        {datasets.isError ? (
          <ErrorPanel error={datasets.error} onRetry={() => void datasets.refetch()} />
        ) : null}
        {datasets.isSuccess ? (
          <CatalogTable
            datasets={filterDatasets(datasets.data, search)}
            selected={search.dataset ?? null}
            rightsFilter={search.rights ?? "all"}
            onSelect={(datasetId) =>
              updateSearch({ dataset: datasetId === search.dataset ? undefined : datasetId })
            }
          />
        ) : null}
      </Panel>
      <Panel title="Dataset detail" className="min-w-0 flex-[2]">
        {search.dataset ? (
          <DatasetPane datasetId={search.dataset} />
        ) : (
          <StatePanel
            state="empty"
            title="No dataset selected."
            detail="Select a row to inspect versions, rights, sessions and the entry into the laboratory."
          />
        )}
      </Panel>
    </div>
  );
}

function CatalogTable({
  datasets,
  selected,
  rightsFilter,
  onSelect,
}: {
  datasets: readonly DatasetSummary[];
  selected: string | null;
  rightsFilter: "all" | "commercial" | "noncommercial";
  onSelect: (datasetId: string) => void;
}) {
  const visible = datasets.filter((dataset) => {
    if (rightsFilter === "all") return true;
    const noncommercial = dataset.license.noncommercial_only;
    return rightsFilter === "noncommercial" ? !noncommercial : noncommercial;
  });
  const columns: DataTableColumn<DatasetSummary>[] = [
    {
      id: "dataset",
      header: "Dataset",
      size: 2.2,
      accessor: (dataset) => dataset.name,
      cell: (dataset) => (
        <span className="min-w-0">
          <span className="block truncate text-text-primary">{dataset.name}</span>
          <span className="mono block truncate text-[10px] text-text-muted">
            {dataset.dataset_id}
          </span>
        </span>
      ),
    },
    {
      id: "modalities",
      header: "Modalities",
      size: 1.6,
      accessor: (dataset) => dataset.modalities.join(","),
      cell: (dataset) => (
        <span className="flex flex-wrap gap-1">
          {dataset.modalities.map((modality) => (
            <ModalityBadge key={modality} modality={modality} />
          ))}
        </span>
      ),
    },
    {
      id: "license",
      header: "License",
      size: 1.6,
      accessor: (dataset) => dataset.license.identifier ?? "unclear",
      cell: (dataset) => (
        <span>
          <span className="block text-text-secondary">
            {dataset.license.identifier ?? "unclear (local-only)"}
          </span>
          {dataset.license.noncommercial_only || dataset.license.local_only ? (
            <span className="text-[10px] text-quality-warning">
              {dataset.license.local_only ? "local-only" : "non-commercial"}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      id: "sessions",
      header: "Sessions",
      size: 0.8,
      align: "right",
      accessor: (dataset) => dataset.session_count,
    },
    {
      id: "metrics",
      header: "Metrics",
      size: 0.8,
      align: "right",
      accessor: (dataset) => dataset.metric_count,
    },
    {
      id: "quality",
      header: "Quarantine",
      size: 0.9,
      align: "right",
      accessor: (dataset) => dataset.quality_issue_count,
    },
  ];
  return (
    <DataTable
      ariaLabel="Registered datasets"
      rows={visible}
      columns={columns}
      getRowId={(dataset) => dataset.dataset_id}
      selectedRowId={selected}
      onRowClick={(dataset) => onSelect(dataset.dataset_id)}
      emptyState={<StatePanel state="empty" title="No dataset matches the current filters." />}
    />
  );
}

function DatasetPane({ datasetId }: { datasetId: string }) {
  const dataset = useQuery(datasetQuery(datasetId));
  const sessions = useQuery(sessionsQuery(datasetId));
  if (dataset.isPending || sessions.isPending) {
    return <LoadingPanel label="Loading dataset detail" />;
  }
  if (dataset.isError) {
    return <ErrorPanel error={dataset.error} onRetry={() => void dataset.refetch()} />;
  }
  const detail = dataset.data;
  return (
    <div className="p-3">
      <SectionTitle>Identity &amp; rights</SectionTitle>
      <dl>
        <KeyValueRow label="dataset" mono>
          {detail.dataset_id}
        </KeyValueRow>
        <KeyValueRow label="provider">{detail.provider}</KeyValueRow>
        <KeyValueRow label="domain">{detail.domain}</KeyValueRow>
        <KeyValueRow label="v1 role">{detail.v1_role}</KeyValueRow>
        <KeyValueRow label="scope">{detail.initial_scope}</KeyValueRow>
        <KeyValueRow label="adapter" mono>
          {detail.adapter_id}
        </KeyValueRow>
      </dl>
      <div className="mt-2 rounded-control border border-border-subtle bg-surface-0 p-2">
        <div className="flex items-center justify-between">
          <span className="mono text-[12px]">{detail.license.identifier ?? "unclear"}</span>
          <MeasurementClassBadge measurementClass="SOURCE_DERIVED" compact />
        </div>
        <p className="mt-1 text-[11px] text-text-muted">{detail.license.notice}</p>
      </div>

      <SectionTitle>Versions</SectionTitle>
      <ul className="space-y-1">
        {detail.versions.map((version) => (
          <li
            key={version.version}
            className="flex items-center justify-between rounded-control border border-border-subtle px-2 py-1 text-[11px]"
          >
            <span className="mono truncate">{version.version}</span>
            <span className="text-text-muted">{version.retrieval_status}</span>
          </li>
        ))}
      </ul>

      <SectionTitle>Sessions</SectionTitle>
      {sessions.isError ? (
        <ErrorPanel error={sessions.error} onRetry={() => void sessions.refetch()} />
      ) : sessions.data.length === 0 ? (
        <StatePanel state="empty" title="No canonical session has been ingested yet." />
      ) : (
        <ul className="space-y-1">
          {sessions.data.map((session) => (
            <li key={session.session_id}>
              <Link
                to="/lab/$datasetId/$sessionId"
                params={{ datasetId: detail.dataset_id, sessionId: session.session_id }}
                className="flex items-center justify-between rounded-control border border-border-subtle px-2 py-1.5 text-[12px] hover:border-border-strong hover:bg-surface-2"
              >
                <span className="min-w-0">
                  <span className="block truncate">{session.label ?? session.session_id}</span>
                  <span className="mono text-[10px] text-text-muted">
                    {session.session_id} · {session.kind}
                  </span>
                </span>
                <span className="text-[10px] text-text-muted">
                  {session.trial_count} trials · {session.stream_count} streams
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
