import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowRight, Scale, Search } from "lucide-react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { CopyableId } from "@/components/common/CopyableId";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { KeyValueRow, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { datasetQuery, datasetsQuery, sessionsQuery } from "@/lib/api/queries";
import type { DatasetSummary } from "@/api/types";
import {
  datasetHasEvents,
  datasetSurfaces,
  LAB_SURFACE_LABELS,
  type LabSurface,
} from "@/lib/capabilities";
import { cn } from "@/lib/cn";
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
  const rights = search.rights ?? "all";
  return datasets.filter((dataset) => {
    if (query) {
      const haystack = `${dataset.dataset_id} ${dataset.name} ${dataset.provider}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    if (search.modality && !dataset.modalities.includes(search.modality)) return false;
    if (rights !== "all") {
      const noncommercial = dataset.license.noncommercial_only;
      if (rights === "noncommercial" ? noncommercial : !noncommercial) return false;
    }
    return true;
  });
}

export interface PlatformScale {
  readonly datasets: number;
  readonly sessions: number;
  readonly trials: number;
  readonly metrics: number;
  readonly modalities: number;
}

/** Aggregate the real registered scale of the platform for the product header. */
export function platformScale(datasets: readonly DatasetSummary[]): PlatformScale {
  const modalities = new Set<string>();
  let sessions = 0;
  let trials = 0;
  let metrics = 0;
  for (const dataset of datasets) {
    sessions += dataset.session_count;
    trials += dataset.trial_count;
    metrics += dataset.metric_count;
    for (const modality of dataset.modalities) modalities.add(modality);
  }
  return { datasets: datasets.length, sessions, trials, metrics, modalities: modalities.size };
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

  const visible = datasets.isSuccess ? filterDatasets(datasets.data, search) : [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ProductHeader datasets={datasets.data ?? []} loaded={datasets.isSuccess} />

      <div className="flex min-h-0 flex-1">
        <section
          aria-label="Dataset catalog"
          className={cn(
            "flex min-w-0 flex-col",
            // Before a selection the catalog owns the whole surface: an
            // unselected detail pane must not reserve flagship width.
            search.dataset ? "flex-[3] border-r border-border-subtle" : "flex-1",
          )}
        >
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border-subtle bg-surface-1 px-3 py-2">
            <label className="relative flex items-center">
              <Search
                size={13}
                aria-hidden="true"
                className="pointer-events-none absolute left-2 text-text-muted"
              />
              <input
                value={search.q ?? ""}
                onChange={(event) => updateSearch({ q: event.target.value || undefined })}
                placeholder="Filter datasets and providers"
                aria-label="Filter datasets"
                className="h-7 w-64 rounded-control border border-border-subtle bg-surface-0 pl-7 pr-2 text-[12px] outline-none transition-colors duration-quick focus:border-accent"
              />
            </label>
            <FilterSelect
              label="Modality"
              value={search.modality ?? ""}
              onChange={(value) =>
                updateSearch({ modality: (value || undefined) as CatalogSearch["modality"] })
              }
              options={[
                { value: "", label: "All modalities" },
                ...MODALITIES.map((modality) => ({ value: modality, label: modality })),
              ]}
            />
            <FilterSelect
              label="Rights"
              value={search.rights ?? "all"}
              onChange={(value) => updateSearch({ rights: value as CatalogSearch["rights"] })}
              options={[
                { value: "all", label: "Any rights" },
                { value: "noncommercial", label: "Non-commercial only" },
                { value: "commercial", label: "Commercial use allowed" },
              ]}
            />
            <span className="ml-auto text-[11px] tabular text-text-muted">
              {datasets.isSuccess
                ? `${visible.length} of ${datasets.data.length} datasets`
                : " "}
            </span>
          </div>

          <div className="min-h-0 flex-1">
            {datasets.isPending ? <LoadingPanel label="Loading dataset catalog" /> : null}
            {datasets.isError ? (
              <ErrorPanel error={datasets.error} onRetry={() => void datasets.refetch()} />
            ) : null}
            {datasets.isSuccess ? (
              <CatalogTable
                datasets={visible}
                selected={search.dataset ?? null}
                onSelect={(datasetId) =>
                  updateSearch({ dataset: datasetId === search.dataset ? undefined : datasetId })
                }
              />
            ) : null}
          </div>
        </section>

        {search.dataset ? (
          <aside
            aria-label="Dataset detail"
            className="flex min-w-0 flex-[2] flex-col bg-surface-1"
          >
            <DatasetPane datasetId={search.dataset} />
          </aside>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Product header: what this is, and the real registered scale behind it. Every
 * number is summed from the served catalog, so the header can never advertise
 * data the platform does not hold.
 */
function ProductHeader({
  datasets,
  loaded,
}: {
  datasets: readonly DatasetSummary[];
  loaded: boolean;
}) {
  const scale = platformScale(datasets);
  return (
    <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-3">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="t-product-title">
            Multimodal human performance data
          </h1>
          <p className="mt-0.5 max-w-2xl text-[12px] text-text-secondary">
            Open scientific datasets ingested to canonical contracts, processed by versioned
            deterministic processors, and served with method, provenance, quality and rights
            attached to every value.
          </p>
        </div>
        {loaded ? (
          <dl className="flex shrink-0 items-end gap-5">
            <ScaleStat label="Datasets" value={scale.datasets} />
            <ScaleStat label="Modalities" value={scale.modalities} />
            <ScaleStat label="Sessions" value={scale.sessions} />
            <ScaleStat label="Trials" value={scale.trials} />
            <ScaleStat label="Derived metrics" value={scale.metrics} />
          </dl>
        ) : null}
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-text-muted">
        <span>Laboratories:</span>
        {(["signals", "field", "pose"] as const).map((surface) => (
          <span
            key={surface}
            className="rounded-[3px] border border-border-subtle px-1.5 py-px text-text-secondary"
          >
            {LAB_SURFACE_LABELS[surface]}
          </span>
        ))}
        <span className="text-border-strong">·</span>
        <span>Evidence: methodology, provenance, quality, rights</span>
      </p>
    </header>
  );
}

function ScaleStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-right">
      <dd className="t-value mono tabular">
        {value.toLocaleString("en-US")}
      </dd>
      <dt className="t-section mt-1 text-text-muted">{label}</dt>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
      {label}
      <select
        aria-label={`Filter by ${label.toLowerCase()}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-7 rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[12px] text-text-secondary outline-none transition-colors duration-quick focus:border-accent"
      >
        {options.map((option) => (
          <option key={option.value || "any"} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Compact non-color-only capability marks for the catalog row. */
function SurfaceMarks({ dataset }: { dataset: DatasetSummary }) {
  const surfaces = datasetSurfaces(dataset.modalities, dataset.stream_count);
  const events = datasetHasEvents(dataset.modalities, dataset.stream_count);
  if (surfaces.length === 0 && !events) {
    // No canonical stream exists, so no renderer can open. Derived metrics
    // still resolve through Compare and Methodology.
    return (
      <span className="text-[11px] text-text-muted" title="No canonical stream is ingested; derived metrics remain available">
        metrics only
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {surfaces.map((surface) => (
        <span
          key={surface}
          className="rounded-[3px] border border-border-strong px-1 py-px text-[10px] text-text-secondary"
          title={`${LAB_SURFACE_LABELS[surface]} laboratory available for this dataset`}
        >
          {LAB_SURFACE_LABELS[surface]}
        </span>
      ))}
      {events ? (
        <span
          className="rounded-[3px] border border-border-subtle px-1 py-px text-[10px] text-text-muted"
          title="Discrete event data available"
        >
          Events
        </span>
      ) : null}
    </span>
  );
}

const CATALOG_COLUMNS: DataTableColumn<DatasetSummary>[] = [
  {
    id: "dataset",
    header: "Dataset",
    size: 4.6,
    accessor: (dataset) => dataset.name,
    cell: (dataset) => (
      <span className="min-w-0">
        <span
          className="block truncate text-[13px] text-text-primary"
          title={dataset.name}
        >
          {dataset.name}
        </span>
        <span className="block truncate text-[11px] text-text-muted" title={dataset.provider}>
          {dataset.provider}
        </span>
      </span>
    ),
  },
  {
    id: "modalities",
    header: "Modalities",
    size: 1.5,
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
    id: "surfaces",
    header: "Laboratories",
    size: 1.6,
    accessor: (dataset) => datasetSurfaces(dataset.modalities, dataset.stream_count).join(","),
    cell: (dataset) => <SurfaceMarks dataset={dataset} />,
  },
  {
    id: "license",
    header: "Rights",
    size: 1.3,
    accessor: (dataset) => dataset.license.identifier ?? "unclear",
    cell: (dataset) => (
      <span className="min-w-0">
        <span className="block truncate text-[12px] text-text-secondary">
          {dataset.license.identifier ?? "Unclear (local-only)"}
        </span>
        {dataset.license.noncommercial_only || dataset.license.local_only ? (
          <span className="flex items-center gap-1 text-[10px] text-quality-warning">
            <Scale size={9} aria-hidden="true" />
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
    cell: (dataset) => (
      <span className="mono text-[12px] tabular">{dataset.session_count.toLocaleString("en-US")}</span>
    ),
  },
  {
    id: "metrics",
    header: "Metrics",
    size: 0.9,
    align: "right",
    accessor: (dataset) => dataset.metric_count,
    cell: (dataset) => (
      <span className="mono text-[12px] tabular">{dataset.metric_count.toLocaleString("en-US")}</span>
    ),
  },
];

function CatalogTable({
  datasets,
  selected,
  onSelect,
}: {
  datasets: readonly DatasetSummary[];
  selected: string | null;
  onSelect: (datasetId: string) => void;
}) {
  return (
    <DataTable
      ariaLabel="Registered datasets"
      rows={datasets}
      columns={CATALOG_COLUMNS}
      // Two-line identity cells need a row tall enough to hold them; a shorter
      // row clips the provider line.
      rowHeight={46}
      getRowId={(dataset) => dataset.dataset_id}
      selectedRowId={selected}
      onRowClick={(dataset) => onSelect(dataset.dataset_id)}
      emptyState={
        <StatePanel
          state="empty"
          title="No dataset matches the current filters."
          detail="Clear the search text, modality or rights filter to see the full registry."
        />
      }
    />
  );
}

function DatasetPane({ datasetId }: { datasetId: string }) {
  const dataset = useQuery(datasetQuery(datasetId));
  const sessions = useQuery(sessionsQuery(datasetId));
  if (dataset.isPending) {
    return <LoadingPanel label="Loading dataset detail" />;
  }
  if (dataset.isError) {
    return <ErrorPanel error={dataset.error} onRetry={() => void dataset.refetch()} />;
  }
  const detail = dataset.data;
  const surfaces = datasetSurfaces(detail.modalities, detail.stream_count);
  const firstSession = sessions.data?.[0] ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-border-subtle px-4 py-3">
        <h2 className="t-analysis-title">{detail.name}</h2>
        <p className="mt-0.5 text-[12px] text-text-secondary">
          {detail.provider} · {detail.domain}
        </p>
        <CopyableId value={detail.dataset_id} label="dataset id" className="mt-1" />

        {firstSession ? (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Link
              to="/lab/$datasetId/$sessionId"
              params={{ datasetId: detail.dataset_id, sessionId: firstSession.session_id }}
              className="inline-flex items-center gap-1.5 rounded-control bg-accent px-2.5 py-1.5 text-[12px] font-medium text-text-inverse transition-colors duration-quick hover:bg-accent-strong"
            >
              Open in laboratory
              <ArrowRight size={13} aria-hidden="true" />
            </Link>
            {surfaces.map((surface) => (
              <SurfaceLink
                key={surface}
                datasetId={detail.dataset_id}
                sessionId={firstSession.session_id}
                surface={surface}
              />
            ))}
          </div>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="border-b border-border-subtle p-3">
          <div className="flex items-start justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5">
              <Scale size={13} aria-hidden="true" className="shrink-0 text-text-muted" />
              <span className="text-[13px] text-text-primary">
                {detail.license.identifier ?? "Unclear rights (local-only)"}
              </span>
            </span>
            <MeasurementClassBadge measurementClass="SOURCE_DERIVED" compact />
          </div>
          <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
            {detail.license.notice}
          </p>
        </div>

        <div className="p-3">
          <SectionTitle>Registry</SectionTitle>
          <dl>
            <KeyValueRow label="V1 role">{detail.v1_role}</KeyValueRow>
            <KeyValueRow label="Scope">{detail.initial_scope}</KeyValueRow>
            <KeyValueRow label="Adapter" mono>
              {detail.adapter_id}
            </KeyValueRow>
            {detail.doi ? (
              <KeyValueRow label="DOI" mono>
                {detail.doi}
              </KeyValueRow>
            ) : null}
          </dl>

          <SectionTitle>Versions</SectionTitle>
          <ul className="mb-3 space-y-1">
            {detail.versions.map((version) => (
              <li
                key={version.version}
                className="flex items-center justify-between gap-2 rounded-control border border-border-subtle px-2 py-1 text-[11px]"
              >
                <span className="mono truncate text-text-secondary">{version.version}</span>
                <span className="shrink-0 text-text-muted">{version.retrieval_status}</span>
              </li>
            ))}
          </ul>

          <SectionTitle>Sessions</SectionTitle>
          {sessions.isPending ? (
            <p className="text-[11px] text-text-muted">Loading sessions…</p>
          ) : sessions.isError ? (
            <ErrorPanel error={sessions.error} onRetry={() => void sessions.refetch()} />
          ) : sessions.data.length === 0 ? (
            <p className="text-[11px] text-text-muted">
              No canonical session has been ingested for this dataset yet.
            </p>
          ) : (
            <ul className="space-y-1">
              {sessions.data.slice(0, 40).map((session) => (
                <li key={session.session_id}>
                  <Link
                    to="/lab/$datasetId/$sessionId"
                    params={{ datasetId: detail.dataset_id, sessionId: session.session_id }}
                    className="flex items-center justify-between gap-2 rounded-control border border-border-subtle px-2 py-1.5 transition-colors duration-quick hover:border-border-strong hover:bg-surface-2"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[12px] text-text-secondary">
                        {session.label ?? session.session_id}
                      </span>
                      <span className="mono block truncate text-[10px] text-text-muted">
                        {session.session_id}
                      </span>
                    </span>
                    <span className="shrink-0 text-[10px] tabular text-text-muted">
                      {session.trial_count} trials · {session.stream_count} streams
                    </span>
                  </Link>
                </li>
              ))}
              {sessions.data.length > 40 ? (
                <li className="px-2 pt-1 text-[10px] text-text-muted">
                  {sessions.data.length - 40} further sessions; filter in the laboratory explorer.
                </li>
              ) : null}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function SurfaceLink({
  datasetId,
  sessionId,
  surface,
}: {
  datasetId: string;
  sessionId: string;
  surface: LabSurface;
}) {
  return (
    <Link
      to="/lab/$datasetId/$sessionId"
      params={{ datasetId, sessionId }}
      search={{ view: surface }}
      className="rounded-control border border-border-subtle px-2 py-1.5 text-[12px] text-text-secondary transition-colors duration-quick hover:border-border-strong hover:bg-surface-2"
      title={`Open the ${LAB_SURFACE_LABELS[surface]} laboratory for this dataset`}
    >
      {LAB_SURFACE_LABELS[surface]}
    </Link>
  );
}
