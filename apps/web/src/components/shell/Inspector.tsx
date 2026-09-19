import { Tabs } from "@base-ui/react/tabs";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { lazy, Suspense } from "react";

import { MeasurementClassBadge, QualityBadge } from "@/components/common/Badges";
import { KeyValueRow, Panel, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { useAnalysisContext } from "@/lib/analysis-context";
import { methodologyQuery, provenanceQuery, qualityQuery, rightsQuery } from "@/lib/api/queries";

// React Flow stays out of the shell chunk: only the provenance tab pays for it.
const LineageGraph = lazy(() => import("@/components/lineage/LineageGraph"));

const INSPECTOR_TABS = [
  ["method", "Method"],
  ["provenance", "Provenance"],
  ["quality", "Quality"],
  ["rights", "Rights"],
] as const;

/**
 * The inspector follows the committed selection: methodology of the selected
 * metric, the exact selected-result lineage, quality issues in scope and the
 * governing rights policy. Text is the primary detail surface.
 */
export function Inspector() {
  return (
    <Panel
      title="Inspector"
      className="border-l border-border-subtle"
      bodyClassName="overflow-y-auto"
    >
      <Tabs.Root defaultValue="method" className="flex min-h-full flex-col">
        <Tabs.List className="sticky top-0 z-10 flex shrink-0 border-b border-border-subtle bg-surface-1">
          {INSPECTOR_TABS.map(([value, label]) => (
            <Tabs.Tab
              key={value}
              value={value}
              className="border-b-2 border-transparent px-3 py-1.5 text-[12px] text-text-muted data-[selected]:border-accent data-[selected]:text-text-primary"
            >
              {label}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        <Tabs.Panel value="method" className="min-h-0 flex-1">
          <MethodTab />
        </Tabs.Panel>
        <Tabs.Panel value="provenance" className="min-h-0 flex-1">
          <ProvenanceTab />
        </Tabs.Panel>
        <Tabs.Panel value="quality" className="min-h-0 flex-1">
          <QualityTab />
        </Tabs.Panel>
        <Tabs.Panel value="rights" className="min-h-0 flex-1">
          <RightsTab />
        </Tabs.Panel>
      </Tabs.Root>
    </Panel>
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
        detail="Select a metric in an analytical view to inspect its definition, algorithm revision and parameters."
      />
    );
  }
  return <MethodForMetric metricId={metricId} />;
}

function MethodForMetric({ metricId }: { metricId: string }) {
  const query = useQuery(methodologyQuery(metricId));
  if (query.isPending) return <LoadingPanel label="Loading metric methodology" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  const data = query.data;
  return (
    <div className="p-3">
      <SectionTitle>Definition</SectionTitle>
      <dl>
        <KeyValueRow label="metric id" mono>
          {data.metric.metric_id}
        </KeyValueRow>
        <KeyValueRow label="SI unit" mono>
          {data.metric.si_unit}
        </KeyValueRow>
        <KeyValueRow label="class">
          <MeasurementClassBadge measurementClass={data.metric.measurement_class} />
        </KeyValueRow>
        <KeyValueRow label="meaning">{data.measurement_class_semantics}</KeyValueRow>
        {data.metric.description ? (
          <KeyValueRow label="definition">{data.metric.description}</KeyValueRow>
        ) : null}
      </dl>
      {data.algorithm ? (
        <>
          <SectionTitle>Algorithm</SectionTitle>
          <dl>
            <KeyValueRow label="algorithm" mono>
              {data.algorithm.algorithm_id}
            </KeyValueRow>
            <KeyValueRow label="version" mono>
              {data.algorithm.version}
            </KeyValueRow>
            <KeyValueRow label="code sha" mono>
              {data.algorithm.code_git_sha ?? "unknown (development-only state)"}
            </KeyValueRow>
            <KeyValueRow label="params sha" mono>
              {data.algorithm.parameters_hash ?? "—"}
            </KeyValueRow>
          </dl>
          <SectionTitle>Parameters</SectionTitle>
          <pre className="mono overflow-x-auto rounded-control border border-border-subtle bg-surface-0 p-2 text-[11px] text-text-secondary">
            {JSON.stringify(data.algorithm.parameters, null, 2)}
          </pre>
        </>
      ) : null}
      <SectionTitle>What this class never means</SectionTitle>
      <ul className="list-disc space-y-1 pl-4 text-[12px] text-text-muted">
        {data.measurement_class_never_means.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
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
  const graph = query.data;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <Suspense fallback={<LoadingPanel label="Loading lineage renderer" />}>
        <LineageGraph graph={graph} />
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
      <StatePanel
        state="empty"
        title="No quality issues recorded for this selection."
        detail="Absence of a recorded issue is not proof of validity; it means no rule flagged this scope."
      />
    );
  }
  return (
    <div className="p-3">
      <ul className="space-y-1">
        {query.data.rows.map((issue) => (
          <li
            key={issue.issue_id}
            className="rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="mono text-[11px] text-text-secondary">{issue.rule}</span>
              <QualityBadge
                state={
                  issue.state === "QUARANTINED"
                    ? "quarantined"
                    : issue.severity === "WARNING"
                      ? "warning"
                      : "valid"
                }
                label={issue.severity}
              />
            </div>
            <div className="mt-1 text-[11px] text-text-muted">
              {issue.stream_id ?? "session scope"}
              {issue.sample_index !== null ? ` · sample ${issue.sample_index}` : ""}
            </div>
          </li>
        ))}
      </ul>
    </div>
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
      {policies.map((policy) => (
        <div key={policy.license.policy_id} className="mb-3">
          <div className="mb-1 flex items-center gap-2">
            <ShieldAlert size={13} aria-hidden="true" className="text-quality-warning" />
            <span className="mono text-[12px] text-text-secondary">
              {policy.license.identifier ?? "unclear rights"}
            </span>
          </div>
          <p className="text-[11px] text-text-muted">{policy.license.notice}</p>
          <p className="mono mt-1 text-[10px] text-text-muted">
            {policy.dataset_ids.join(", ")}
          </p>
        </div>
      ))}
      <a className="inline-flex items-center gap-1 text-[11px] text-accent" href="/quality">
        Open Quality &amp; Rights
      </a>
    </div>
  );
}
