import { Tabs } from "@base-ui/react/tabs";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { PanelRightClose, Scale } from "lucide-react";
import { lazy, Suspense } from "react";

import { MeasurementClassBadge } from "@/components/common/Badges";
import { CopyableId } from "@/components/common/CopyableId";
import { Panel } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { MetricValue, QualityIssueView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import {
  methodologyQuery,
  metricsQuery,
  provenanceQuery,
  qualityQuery,
  rightsQuery,
} from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { formatMetricValue, QUALITY_STATES, qualityStateFor } from "@/lib/measurement";

// React Flow stays out of the shell chunk: only the provenance tab pays for it.
const LineageGraph = lazy(() => import("@/components/lineage/LineageGraph"));

const INSPECTOR_TABS = [
  ["method", "Method"],
  ["provenance", "Provenance"],
  ["quality", "Quality"],
  ["rights", "Rights"],
] as const;

/**
 * The evidence pane follows the committed selection.
 *
 * The selected result's identity stays pinned above the tabs, so whichever
 * evidence a reader is on, they can see which value it belongs to. Text is the
 * primary detail surface; exact hashes and revisions are copyable but never
 * the loudest thing on screen.
 */
export function Inspector({ onCollapse }: { onCollapse?: () => void } = {}) {
  return (
    <Panel
      title="Inspector"
      className="border-l border-border-subtle"
      bodyClassName="flex flex-col overflow-hidden"
      actions={
        onCollapse ? (
          <button
            type="button"
            onClick={onCollapse}
            aria-label="Collapse the inspector"
            title="Collapse the inspector"
            className="flex size-5 items-center justify-center rounded-[3px] text-text-muted transition-colors duration-quick hover:bg-surface-2 hover:text-text-secondary"
          >
            <PanelRightClose size={13} aria-hidden="true" />
          </button>
        ) : null
      }
    >
      <SelectedResultHeader />
      <Tabs.Root defaultValue="method" className="flex min-h-0 flex-1 flex-col">
        <Tabs.List className="flex shrink-0 border-b border-border-subtle bg-surface-1">
          {INSPECTOR_TABS.map(([value, label]) => (
            <Tabs.Tab
              key={value}
              value={value}
              className="border-b-2 border-transparent px-3 py-1.5 text-[12px] text-text-muted transition-colors duration-quick hover:text-text-secondary data-[selected]:border-accent data-[selected]:font-medium data-[selected]:text-text-primary"
            >
              {label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        <Tabs.Panel value="method" className="min-h-0 flex-1 overflow-y-auto">
          <MethodTab />
        </Tabs.Panel>
        <Tabs.Panel value="provenance" className="min-h-0 flex-1 overflow-hidden">
          <ProvenanceTab />
        </Tabs.Panel>
        <Tabs.Panel value="quality" className="min-h-0 flex-1 overflow-y-auto">
          <QualityTab />
        </Tabs.Panel>
        <Tabs.Panel value="rights" className="min-h-0 flex-1 overflow-y-auto">
          <RightsTab />
        </Tabs.Panel>
      </Tabs.Root>
    </Panel>
  );
}

/**
 * Which value the evidence belongs to.
 *
 * Pinned above the tabs so the identity never scrolls away while a reader
 * moves between method, provenance, quality and rights.
 */
function SelectedResultHeader() {
  const context = useAnalysisContext();
  const resultId = context?.derivedMetricId ?? null;
  const query = useQuery({
    ...metricsQuery({ datasetId: context?.datasetId, limit: 1000 }),
    enabled: Boolean(context && resultId),
  });
  const row: MetricValue | null =
    resultId === null
      ? null
      : (query.data?.rows.find((candidate) => candidate.derived_metric_id === resultId) ?? null);

  if (resultId === null) return null;
  return (
    <div className="shrink-0 border-b border-border-subtle bg-surface-0 px-3 py-2">
      {row ? (
        <>
          <div className="flex items-baseline justify-between gap-2">
            <span
              className="min-w-0 truncate text-[12px] text-text-primary"
              title={row.metric_name ?? row.metric_id}
            >
              {row.metric_name ?? row.metric_id}
            </span>
            <span className="t-value mono shrink-0 tabular">
              {formatMetricValue(row.value_num, row.si_unit).text}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="mono min-w-0 truncate text-[10px] text-text-muted" title={row.metric_id}>
              {[row.session_id, row.trial_id, row.subject_id]
                .filter((part): part is string => Boolean(part))
                .join(" / ")}
            </span>
            <MeasurementClassBadge measurementClass={row.measurement_class} compact />
          </div>
        </>
      ) : (
        <CopyableId value={resultId} label="result id" />
      )}
    </div>
  );
}

function MethodTab() {
  const context = useAnalysisContext();
  const metricId = context?.metricId ?? null;
  if (!metricId) {
    return (
      <StatePanel
        state="empty"
        title="No metric selected."
        detail="Select a value in a chart or table to read its definition, algorithm revision and parameters."
      />
    );
  }
  return <MethodForMetric metricId={metricId} />;
}

function MethodForMetric({ metricId }: { metricId: string }) {
  const query = useQuery(methodologyQuery(metricId));
  if (query.isPending) return <LoadingPanel label="Loading metric methodology" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  const { metric, algorithm } = query.data;
  return (
    <div className="p-3">
      <h3 className="t-analysis-title">{metric.name}</h3>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <MeasurementClassBadge measurementClass={metric.measurement_class} compact />
        <span className="rounded-[3px] border border-border-subtle px-1.5 py-px text-[11px] text-text-secondary">
          {metric.si_unit === "1" ? "dimensionless" : metric.si_unit}
        </span>
      </div>
      <CopyableId value={metric.metric_id} label="metric id" className="mt-1.5" />

      {metric.description ? (
        <p className="mt-3 text-[12px] leading-relaxed text-text-secondary">
          {metric.description}
        </p>
      ) : null}

      <InspectorSection title="Measurement class">
        <p className="text-[12px] leading-relaxed text-text-secondary">
          {query.data.measurement_class_semantics}
        </p>
        <ul className="mt-2 space-y-1">
          {query.data.measurement_class_never_means.map((line) => (
            <li key={line} className="flex gap-1.5 text-[11px] leading-relaxed text-text-muted">
              <span aria-hidden="true" className="shrink-0 text-quality-warning">
                ▲
              </span>
              {line}
            </li>
          ))}
        </ul>
      </InspectorSection>

      {algorithm ? (
        <InspectorSection title="Algorithm">
          <p className="text-[12px] text-text-secondary">
            {algorithm.name}{" "}
            <span className="mono text-[11px] text-text-muted">v{algorithm.version}</span>
          </p>
          <dl className="mt-2 space-y-1">
            <EvidenceRow label="Code revision" value={algorithm.code_git_sha} />
            <EvidenceRow label="Parameters hash" value={algorithm.parameters_hash} />
          </dl>
          <Link
            to="/methods"
            search={{ metric: metric.metric_id }}
            className="mt-2 inline-block text-[11px] text-accent hover:underline"
          >
            Open full methodology →
          </Link>
        </InspectorSection>
      ) : null}
    </div>
  );
}

function ProvenanceTab() {
  const context = useAnalysisContext();
  const resultId = context?.derivedMetricId ?? null;
  const query = useQuery({ ...provenanceQuery(resultId ?? ""), enabled: Boolean(resultId) });
  if (!resultId) {
    return (
      <StatePanel
        state="empty"
        title="No result selected."
        detail="Select a computed value to open its exact source → artifact → stream → processor → run → result lineage."
      />
    );
  }
  if (query.isPending) return <LoadingPanel label="Loading provenance lineage" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Suspense fallback={<LoadingPanel label="Loading lineage renderer" />}>
        <LineageGraph graph={query.data} />
      </Suspense>
    </div>
  );
}

function QualityTab() {
  const context = useAnalysisContext();
  const query = useQuery(
    qualityQuery({
      datasetId: context?.datasetId,
      sessionId: context?.sessionId,
      limit: 50,
    }),
  );
  if (query.isPending) return <LoadingPanel label="Loading quality context" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data.total === 0) {
    return (
      <div className="p-3">
        <div className="flex items-center gap-2 rounded-control border border-border-subtle bg-surface-0 px-2.5 py-2">
          <span aria-hidden="true" style={{ color: QUALITY_STATES.valid.token }}>
            {QUALITY_STATES.valid.glyph}
          </span>
          <span className="text-[12px] text-text-secondary">No rule flagged this scope</span>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          Absence of a recorded issue is not proof of validity; it means no quality rule flagged
          the selected dataset and session.
        </p>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-border-subtle/60">
      {query.data.rows.map((issue) => (
        <li key={issue.issue_id} className="px-3 py-2">
          <QualityRow issue={issue} />
        </li>
      ))}
    </ul>
  );
}

function QualityRow({ issue }: { issue: QualityIssueView }) {
  const state = qualityStateFor(issue.severity, issue.state);
  const descriptor = QUALITY_STATES[state];
  return (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <span className="flex min-w-0 items-baseline gap-1.5">
          <span aria-hidden="true" className="shrink-0" style={{ color: descriptor.token }}>
            {descriptor.glyph}
          </span>
          <span className="truncate text-[12px] text-text-secondary" title={issue.rule}>
            {issue.rule}
          </span>
        </span>
        <span className="shrink-0 text-[11px]" style={{ color: descriptor.token }}>
          {descriptor.label}
        </span>
      </div>
      <p className="mono mt-0.5 truncate text-[10px] text-text-muted">
        {issue.stream_id ?? "session scope"}
        {issue.sample_index !== null ? ` · sample ${issue.sample_index}` : ""}
      </p>
    </>
  );
}

function RightsTab() {
  const context = useAnalysisContext();
  const query = useQuery(rightsQuery());
  if (query.isPending) return <LoadingPanel label="Loading rights context" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  const relevant = query.data.policies.filter(
    (policy) => !context || policy.dataset_ids.includes(context.datasetId),
  );
  const policies = relevant.length > 0 ? relevant : query.data.policies;
  return (
    <div className="p-3">
      {policies.map((policy) => {
        const { license } = policy;
        const restricted = license.noncommercial_only || license.local_only || license.share_alike;
        return (
          <div
            key={license.policy_id}
            className="mb-3 rounded-control border border-border-subtle bg-surface-0 p-2.5 last:mb-0"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <Scale size={13} aria-hidden="true" className="shrink-0 text-text-muted" />
                <span className="truncate text-[13px] text-text-primary">
                  {license.identifier ?? "Unclear rights"}
                </span>
              </span>
              {restricted ? (
                <span className="shrink-0 text-[10px] text-quality-warning">▲ restricted</span>
              ) : null}
            </div>
            <ul className="mt-2 space-y-1 text-[11px]">
              <RightsFlag label="Attribution required" value={license.attribution_required} />
              <RightsFlag label="Commercial use" value={!license.noncommercial_only} />
              <RightsFlag label="Share-alike" value={license.share_alike} invertTone />
              <RightsFlag label="Local-only" value={license.local_only} invertTone />
            </ul>
            <p className="mt-2 text-[11px] leading-relaxed text-text-muted">{license.notice}</p>
            <p className="mono mt-1.5 truncate text-[10px] text-text-muted" title={policy.dataset_ids.join(", ")}>
              {policy.dataset_ids.join(", ")}
            </p>
          </div>
        );
      })}
      <Link to="/quality" className="text-[11px] text-accent hover:underline">
        Open Quality &amp; rights →
      </Link>
    </div>
  );
}

/** A rights flag with a shape cue as well as colour. */
function RightsFlag({
  label,
  value,
  invertTone = false,
}: {
  label: string;
  value: boolean;
  invertTone?: boolean;
}) {
  const concerning = invertTone ? value : !value;
  return (
    <li className="flex items-baseline justify-between gap-2">
      <span className="text-text-muted">{label}</span>
      <span
        className={cn(
          "flex shrink-0 items-center gap-1",
          concerning ? "text-quality-warning" : "text-text-secondary",
        )}
      >
        <span aria-hidden="true">{value ? "●" : "—"}</span>
        {value ? "yes" : "no"}
      </span>
    </li>
  );
}

function InspectorSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-4 border-t border-border-subtle pt-3">
      <h4 className="t-section mb-2 text-text-muted">
        {title}
      </h4>
      {children}
    </section>
  );
}

function EvidenceRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="shrink-0 text-[11px] text-text-muted">{label}</dt>
      <dd className="min-w-0">
        {value ? (
          <CopyableId value={value} label={label.toLowerCase()} className="max-w-40" />
        ) : (
          <span className="text-[11px] text-quality-warning">
            unknown (development-only state)
          </span>
        )}
      </dd>
    </div>
  );
}
