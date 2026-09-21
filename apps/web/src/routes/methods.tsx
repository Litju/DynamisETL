import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { ChevronDown, ChevronRight } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";

import { MeasurementClassBadge } from "@/components/common/Badges";
import { CopyableId } from "@/components/common/CopyableId";
import { MetricPicker } from "@/components/common/MetricPicker";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { MetricMethodology, MetricValue } from "@/api/types";
import {
  metricDefinitionsQuery,
  methodologyQuery,
  metricsQuery,
  provenanceQuery,
} from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { formatMetricValue } from "@/lib/measurement";
import { methodsSearchSchema, parseSearch } from "@/lib/search";
import type { MethodsSearch } from "@/lib/search";

const LineageGraph = lazy(() => import("@/components/lineage/LineageGraph"));

const RESULT_PAGE_LIMIT = 200;

export function defineMethodsRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/methods",
    validateSearch: (search: Record<string, unknown>) => parseSearch(methodsSearchSchema, search),
    component: MethodsPage,
  });
}

/**
 * Methodology and provenance explorer.
 *
 * A reader arrives knowing a question, not an internal identifier. Metrics are
 * discovered from the registered vocabulary, the definition and algorithm
 * populate immediately, and the served results of that metric are offered by
 * their readable scope so a lineage can be opened without anyone typing a
 * `dm-…` id. Hashes and code revisions stay exact, in a secondary layer.
 */
export function MethodsPage() {
  const search = useSearch({ from: "/methods" });
  const navigate = useNavigate();
  const definitions = useQuery(metricDefinitionsQuery());

  const update = (patch: Partial<MethodsSearch>) => {
    void navigate({
      to: "/methods",
      search: (previous: MethodsSearch) => ({ ...previous, ...patch }),
      replace: true,
    });
  };

  const served = useMemo(
    () => (definitions.data ?? []).filter((entry) => entry.value_count > 0),
    [definitions.data],
  );
  const metricId = search.metric ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-3">
        <h1 className="t-surface-title">
          Methodology and provenance
        </h1>
        <p className="mt-0.5 text-[12px] text-text-secondary">
          What a metric means, how it was computed, and which exact run produced any one of its
          values.
        </p>
        <div className="mt-2">
          <MetricPicker
            label="Metric"
            value={metricId}
            options={served}
            isPending={definitions.isPending}
            onChange={(next) => update({ metric: next ?? undefined, result: undefined })}
          />
        </div>
      </header>

      {definitions.isError ? (
        <ErrorPanel error={definitions.error} onRetry={() => void definitions.refetch()} />
      ) : metricId === null ? (
        <StatePanel
          state="empty"
          title="Choose a metric."
          detail="Its definition, measurement class, algorithm revision and parameters appear immediately, together with the served results whose exact lineage you can open."
        />
      ) : (
        <MethodBody
          metricId={metricId}
          resultId={search.result ?? null}
          onSelectResult={(next) => update({ result: next ?? undefined })}
        />
      )}
    </div>
  );
}

function MethodBody({
  metricId,
  resultId,
  onSelectResult,
}: {
  metricId: string;
  resultId: string | null;
  onSelectResult: (resultId: string | null) => void;
}) {
  const methodology = useQuery(methodologyQuery(metricId));
  const results = useQuery(metricsQuery({ metricId, limit: RESULT_PAGE_LIMIT }));

  if (methodology.isPending) return <LoadingPanel label="Loading metric methodology" />;
  if (methodology.isError) {
    return <ErrorPanel error={methodology.error} onRetry={() => void methodology.refetch()} />;
  }

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-px overflow-hidden bg-border-subtle xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <MethodDetail methodology={methodology.data} />
      <div className="flex min-h-0 min-w-0 flex-col bg-surface-1">
        <ResultChooser
          results={results.data?.rows ?? []}
          total={results.data?.total ?? 0}
          isPending={results.isPending}
          selected={resultId}
          onSelect={onSelectResult}
        />
        <div className="min-h-0 flex-1">
          {resultId === null ? (
            <StatePanel
              state="empty"
              title="Choose a served result to open its lineage."
              detail="The graph resolves that exact value back through its run, algorithm, canonical stream and source artifact."
            />
          ) : (
            <SelectedLineage derivedMetricId={resultId} />
          )}
        </div>
      </div>
    </div>
  );
}

/** Definition, class semantics, algorithm and parameters; evidence beneath. */
function MethodDetail({ methodology }: { methodology: MetricMethodology }) {
  const { metric, algorithm } = methodology;
  return (
    <div className="min-h-0 min-w-0 overflow-y-auto bg-surface-1">
      <header className="border-b border-border-subtle px-4 py-3">
        <h2 className="t-analysis-title">{metric.name}</h2>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <MeasurementClassBadge measurementClass={metric.measurement_class} />
          <span className="rounded-[3px] border border-border-subtle px-1.5 py-px text-[11px] text-text-secondary">
            {metric.si_unit === "1" ? "dimensionless" : metric.si_unit}
          </span>
          <span className="text-[11px] text-text-muted">{metric.value_kind}</span>
        </div>
        <CopyableId value={metric.metric_id} label="metric id" className="mt-1.5" />
      </header>

      <Section title="Definition">
        <p className="text-[12px] leading-relaxed text-text-secondary">
          {metric.description ?? "No definition text is registered for this metric."}
        </p>
      </Section>

      <Section title="What this measurement class means">
        <p className="text-[12px] leading-relaxed text-text-secondary">
          {methodology.measurement_class_semantics}
        </p>
        <ul className="mt-2 space-y-1">
          {methodology.measurement_class_never_means.map((line) => (
            <li key={line} className="flex gap-2 text-[11px] leading-relaxed text-text-muted">
              <span aria-hidden="true" className="shrink-0 text-quality-warning">
                ▲
              </span>
              {line}
            </li>
          ))}
        </ul>
      </Section>

      {algorithm ? (
        <>
          <Section title="Algorithm">
            <dl className="space-y-1.5">
              <Row label="Name">{algorithm.name}</Row>
              <Row label="Version" mono>
                {algorithm.version}
              </Row>
              <Row label="Kind">{algorithm.kind}</Row>
              {algorithm.description ? (
                <Row label="Description">{algorithm.description}</Row>
              ) : null}
              {algorithm.citation ? <Row label="Citation">{algorithm.citation}</Row> : null}
            </dl>
          </Section>

          <Section title="Parameters">
            <ParameterSummary parameters={algorithm.parameters} />
          </Section>

          <Disclosure title="Technical evidence">
            <dl className="space-y-1.5">
              <Row label="Algorithm id" mono>
                {algorithm.algorithm_id}
              </Row>
              <EvidenceRow
                label="Code revision"
                value={algorithm.code_git_sha}
                fallback="unknown (development-only state)"
              />
              <EvidenceRow label="Parameters hash" value={algorithm.parameters_hash} />
            </dl>
            <p className="mt-2 text-[10px] leading-relaxed text-text-muted">
              Reference fields carried by every served value:{" "}
              {methodology.provenance_fields.join(", ")}.
            </p>
          </Disclosure>
        </>
      ) : (
        <Section title="Algorithm">
          <p className="text-[12px] text-text-muted">
            No algorithm is registered against this metric definition, so it carries no parameters
            or code revision of its own.
          </p>
        </Section>
      )}
    </div>
  );
}

/**
 * Parameters as readable rows.
 *
 * Nested structures (a processor's segment and angle declarations) are shown
 * as a count with the raw object available, so the summary stays legible
 * without hiding what the run actually used.
 */
function ParameterSummary({ parameters }: { parameters: Record<string, unknown> }) {
  const entries = Object.entries(parameters);
  if (entries.length === 0) {
    return <p className="text-[12px] text-text-muted">This algorithm declares no parameters.</p>;
  }
  return (
    <>
      <dl className="space-y-1.5">
        {entries.map(([key, value]) => (
          <Row key={key} label={key} mono={typeof value !== "object" || value === null}>
            {describeParameter(value)}
          </Row>
        ))}
      </dl>
      <Disclosure title="Exact parameter object" compact>
        <pre className="mono overflow-x-auto rounded-control border border-border-subtle bg-surface-0 p-2 text-[10px] leading-relaxed text-text-secondary">
          {JSON.stringify(parameters, null, 2)}
        </pre>
      </Disclosure>
    </>
  );
}

function describeParameter(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) {
    const names = value
      .map((item) =>
        typeof item === "object" && item !== null && "name" in item
          ? String((item as { name: unknown }).name)
          : null,
      )
      .filter((name): name is string => name !== null);
    return names.length > 0
      ? `${value.length}: ${names.join(", ")}`
      : `${value.length} entries`;
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${key}=${nested === null ? "null" : String(nested)}`)
      .join(", ");
  }
  return String(value);
}

/** The served results of the metric, offered by their readable scope. */
function ResultChooser({
  results,
  total,
  isPending,
  selected,
  onSelect,
}: {
  results: readonly MetricValue[];
  total: number;
  isPending: boolean;
  selected: string | null;
  onSelect: (resultId: string | null) => void;
}) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? results.filter((row) => scopeLabel(row).toLowerCase().includes(needle))
    : results;

  return (
    <div className="shrink-0 border-b border-border-subtle">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2">
        <h2 className="t-analysis-title">Served results</h2>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter by dataset, session, trial or subject"
          aria-label="Filter served results"
          className="h-6 w-64 rounded-control border border-border-subtle bg-surface-0 px-2 text-[11px] outline-none transition-colors duration-quick focus:border-accent"
        />
        <span className="ml-auto text-[10px] tabular text-text-muted">
          {isPending
            ? "loading…"
            : `${visible.length} of ${total.toLocaleString("en-US")}${
                total > results.length ? " (first page)" : ""
              }`}
        </span>
      </div>
      <ul className="max-h-40 overflow-y-auto pb-1">
        {visible.slice(0, 200).map((row) => (
          <li key={row.derived_metric_id}>
            <button
              type="button"
              aria-pressed={row.derived_metric_id === selected}
              onClick={() =>
                onSelect(row.derived_metric_id === selected ? null : row.derived_metric_id)
              }
              className={cn(
                "flex w-full items-baseline justify-between gap-3 border-l-2 px-4 py-1 text-left transition-colors duration-quick hover:bg-surface-2",
                row.derived_metric_id === selected
                  ? "border-accent bg-surface-2"
                  : "border-transparent",
              )}
            >
              <span className="mono min-w-0 flex-1 truncate text-[11px] text-text-secondary">
                {scopeLabel(row)}
              </span>
              <span className="mono shrink-0 tabular text-[11px] text-text-primary">
                {formatMetricValue(row.value_num, row.si_unit).text}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function scopeLabel(row: MetricValue): string {
  return [row.dataset_id, row.session_id, row.trial_id, row.subject_id ?? row.entity_id]
    .filter((part): part is string => typeof part === "string" && part.length > 0)
    .join(" / ");
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border-subtle px-4 py-3">
      <h3 className="t-section mb-2 text-text-muted">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Disclosure({
  title,
  children,
  compact = false,
}: {
  title: string;
  children: React.ReactNode;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className={cn("border-b border-border-subtle", compact ? "mt-2" : "px-4 py-3")}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="t-section flex items-center gap-1.5 text-text-muted hover:text-text-secondary"
      >
        {open ? (
          <ChevronDown size={12} aria-hidden="true" />
        ) : (
          <ChevronRight size={12} aria-hidden="true" />
        )}
        {title}
      </button>
      {open ? <div className="mt-2">{children}</div> : null}
    </section>
  );
}

function Row({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] items-baseline gap-2">
      <dt className="text-[11px] text-text-muted">{label}</dt>
      <dd
        className={cn(
          "min-w-0 break-words text-[12px] leading-relaxed text-text-secondary",
          mono && "mono",
        )}
      >
        {children}
      </dd>
    </div>
  );
}

function EvidenceRow({
  label,
  value,
  fallback = "—",
}: {
  label: string;
  value: string | null;
  fallback?: string;
}) {
  return (
    <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] items-baseline gap-2">
      <dt className="text-[11px] text-text-muted">{label}</dt>
      <dd className="min-w-0">
        {value ? (
          <CopyableId value={value} label={label.toLowerCase()} />
        ) : (
          <span className="text-[11px] text-quality-warning">{fallback}</span>
        )}
      </dd>
    </div>
  );
}
