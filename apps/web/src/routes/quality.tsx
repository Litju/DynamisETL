import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";

import { Panel, SectionTitle } from "@/components/common/Panel";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { qualityQuery, rightsQuery, runsQuery, servingStatusQuery } from "@/lib/api/queries";
import { QUALITY_STATES, qualityStateFor } from "@/lib/measurement";
import { parseSearch, qualitySearchSchema } from "@/lib/search";
import type { QualitySearch } from "@/lib/search";


export function defineQualityRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/quality",
  validateSearch: (search: Record<string, unknown>) => parseSearch(qualitySearchSchema, search),
  component: QualityPage,
});
}

const SEVERITIES = ["", "INFO", "WARNING", "ERROR"] as const;

export function QualityPage() {
  const search = useSearch({ from: "/quality" });
  const navigate = useNavigate();
  const quality = useQuery(
    qualityQuery({
      datasetId: search.dataset,
      sessionId: search.session,
      severity: search.severity,
      limit: 200,
    }),
  );
  const rights = useQuery(rightsQuery());
  const runs = useQuery(runsQuery({ limit: 50 }));
  const status = useQuery(servingStatusQuery());

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-px overflow-auto bg-border-subtle xl:grid-cols-3">
      <Panel title="Quality issues" className="min-h-64">
        <div className="flex items-center gap-2 border-b border-border-subtle p-2">
          <input
            value={search.dataset ?? ""}
            onChange={(event) =>
              void navigate({
                to: "/quality",
                search: (previous: QualitySearch) => ({
                  ...previous,
                  dataset: event.target.value || undefined,
                }),
                replace: true,
              })
            }
            placeholder="dataset id"
            aria-label="Filter quality issues by dataset"
            className="mono h-6 w-48 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px]"
          />
          <select
            aria-label="Filter by severity"
            value={search.severity ?? ""}
            onChange={(event) => {
              const severity = event.target.value;
              void navigate({
                to: "/quality",
                search: (previous: QualitySearch) => ({
                  ...previous,
                  severity:
                    severity === "INFO" || severity === "WARNING" || severity === "ERROR"
                      ? severity
                      : undefined,
                }),
                replace: true,
              });
            }}
            className="mono rounded-control border border-border-subtle bg-surface-0 px-1 py-1 text-[11px]"
          >
            {SEVERITIES.map((severity) => (
              <option key={severity || "all"} value={severity}>
                {severity || "all severities"}
              </option>
            ))}
          </select>
        </div>
        {quality.isPending ? <LoadingPanel label="Loading quality issues" /> : null}
        {quality.isError ? (
          <ErrorPanel error={quality.error} onRetry={() => void quality.refetch()} />
        ) : null}
        {quality.isSuccess ? (
          quality.data.total === 0 ? (
            <StatePanel
              state="empty"
              title="No quality issue recorded for this filter."
              detail="This means no rule flagged the scope; it is not a validity guarantee."
            />
          ) : (
            <ul className="divide-y divide-border-subtle/60">
              {quality.data.rows.map((issue) => {
                const state = qualityStateFor(issue.severity, issue.state);
                const descriptor = QUALITY_STATES[state];
                return (
                  <li key={issue.issue_id} className="px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="mono text-[11px] text-text-secondary">{issue.rule}</span>
                      <span className="text-[11px]" style={{ color: descriptor.token }}>
                        {descriptor.glyph} {issue.severity} · {issue.state}
                      </span>
                    </div>
                    <div className="mt-1 grid grid-cols-2 gap-x-3 text-[11px] text-text-muted">
                      <span className="mono">{issue.dataset_id}</span>
                      <span className="mono">{issue.session_id ?? "session-wide"}</span>
                      <span className="mono">{issue.stream_id ?? "no stream scope"}</span>
                      <span className="mono">
                        {issue.sample_index !== null ? `sample ${issue.sample_index}` : "no sample"}
                      </span>
                    </div>
                    <pre className="mono mt-1 overflow-x-auto rounded-control bg-surface-0 p-1 text-[10px] text-text-muted">
                      {JSON.stringify(issue.evidence)}
                    </pre>
                  </li>
                );
              })}
            </ul>
          )
        ) : null}
      </Panel>

      <Panel title="Rights and licenses" className="min-h-64">
        {rights.isPending ? <LoadingPanel label="Loading rights" /> : null}
        {rights.isError ? (
          <ErrorPanel error={rights.error} onRetry={() => void rights.refetch()} />
        ) : null}
        {rights.isSuccess ? (
          <ul className="divide-y divide-border-subtle/60">
            {rights.data.policies.map((policy) => (
              <li key={policy.license.policy_id} className="px-3 py-2">
                <div className="mono text-[12px]">
                  {policy.license.identifier ?? "unclear (local-only)"}
                </div>
                <p className="mt-1 text-[11px] text-text-muted">{policy.license.notice}</p>
                <p className="mono mt-1 text-[10px] text-text-muted">
                  {policy.dataset_ids.join(", ") || "no dataset"}
                </p>
              </li>
            ))}
          </ul>
        ) : null}
      </Panel>

      <Panel title="Serving state" className="min-h-64">
        <div className="p-3">
          <SectionTitle>Database</SectionTitle>
          {status.isPending ? <LoadingPanel label="Loading serving status" /> : null}
          {status.isError ? (
            <ErrorPanel error={status.error} onRetry={() => void status.refetch()} />
          ) : null}
          {status.isSuccess ? (
            <dl className="text-[12px]">
              <div className="flex justify-between border-b border-border-subtle/60 py-1">
                <dt className="text-text-muted">control schema</dt>
                <dd className="mono">{status.data.db_schema}</dd>
              </div>
              <div className="flex justify-between border-b border-border-subtle/60 py-1">
                <dt className="text-text-muted">gold schema</dt>
                <dd className="mono">{status.data.gold_schema}</dd>
              </div>
              <div className="flex justify-between border-b border-border-subtle/60 py-1">
                <dt className="text-text-muted">gold published</dt>
                <dd className="mono">{status.data.gold_published ? "yes" : "no"}</dd>
              </div>
              <div className="flex justify-between border-b border-border-subtle/60 py-1">
                <dt className="text-text-muted">runs</dt>
                <dd className="mono tabular">{status.data.run_count}</dd>
              </div>
              <div className="flex justify-between py-1">
                <dt className="text-text-muted">quality issues</dt>
                <dd className="mono tabular">{status.data.quality_issue_count}</dd>
              </div>
            </dl>
          ) : null}
          <SectionTitle>Recent runs</SectionTitle>
          {runs.isSuccess ? (
            <ul className="space-y-1">
              {runs.data.rows.slice(0, 8).map((run) => (
                <li key={run.run_id} className="mono text-[11px] text-text-muted">
                  {run.dataset_id} · {run.algorithm_id} ·{" "}
                  {run.code_git_sha ? run.code_git_sha.slice(0, 12) : "unknown SHA"}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-3 text-[11px] text-text-muted">
            NC/SA and local-only sources are never redistributed through this product; rights are
            shown next to the results they govern.
          </p>
        </div>
      </Panel>
    </div>
  );
}
