import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { Scale } from "lucide-react";

import { ErrorPanel, LoadingPanel } from "@/components/common/StatePanel";
import type { DatasetSummary, QualityIssueView, RightsPage } from "@/api/types";
import { datasetsQuery, qualityQuery, rightsQuery, servingStatusQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
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

/**
 * Quality and rights.
 *
 * Two questions a reader must be able to answer from one screen: can I trust
 * this data, and may I use it here. Trust is the recorded quality state of the
 * serving plane; usage is the declared licence of each source, shown as
 * explicit flags rather than a paragraph of registry prose.
 */
export function QualityPage() {
  const search = useSearch({ from: "/quality" });
  const navigate = useNavigate();
  const status = useQuery(servingStatusQuery());
  const datasets = useQuery(datasetsQuery());
  const rights = useQuery(rightsQuery());
  const quality = useQuery(
    qualityQuery({
      datasetId: search.dataset,
      sessionId: search.session,
      severity: search.severity,
      limit: 200,
    }),
  );

  const update = (patch: Partial<QualitySearch>) => {
    void navigate({
      to: "/quality",
      search: (previous: QualitySearch) => ({ ...previous, ...patch }),
      replace: true,
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-3">
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
          <div className="min-w-0">
            <h1 className="text-[16px] font-medium leading-tight text-text-primary">
              Quality &amp; rights
            </h1>
            <p className="mt-0.5 max-w-2xl text-[12px] text-text-secondary">
              What the validation rules recorded about the served data, and the licence terms that
              govern its use.
            </p>
          </div>
          {status.isSuccess ? (
            <dl className="flex shrink-0 flex-wrap items-end gap-5">
              <Stat label="Datasets" value={status.data.dataset_count} />
              <Stat label="Derived metrics" value={status.data.metric_count} />
              <Stat label="Processing runs" value={status.data.run_count} />
              <Stat
                label="Quality issues"
                value={status.data.quality_issue_count}
                tone={status.data.quality_issue_count > 0 ? "warning" : "valid"}
              />
            </dl>
          ) : null}
        </div>
        {status.isSuccess ? (
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-muted">
            <ServingFlag
              label="Gold schema published"
              value={status.data.gold_published}
            />
            <span className="text-border-strong">·</span>
            <span>
              control schema <span className="mono text-text-secondary">{status.data.db_schema}</span>
            </span>
            <span>
              gold schema <span className="mono text-text-secondary">{status.data.gold_schema}</span>
            </span>
          </p>
        ) : null}
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-border-subtle xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <section className="flex min-h-64 min-w-0 flex-col bg-surface-1">
          <header className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border-subtle px-4 py-2">
            <h2 className="text-[13px] font-medium text-text-primary">Recorded quality issues</h2>
            <input
              value={search.dataset ?? ""}
              onChange={(event) => update({ dataset: event.target.value || undefined })}
              placeholder="Filter by dataset"
              aria-label="Filter quality issues by dataset"
              className="mono h-6 w-44 rounded-control border border-border-subtle bg-surface-0 px-2 text-[11px] outline-none focus:border-accent"
            />
            <select
              aria-label="Filter by severity"
              value={search.severity ?? ""}
              onChange={(event) => {
                const severity = event.target.value;
                update({
                  severity:
                    severity === "INFO" || severity === "WARNING" || severity === "ERROR"
                      ? severity
                      : undefined,
                });
              }}
              className="h-6 rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[11px] text-text-secondary outline-none focus:border-accent"
            >
              {SEVERITIES.map((severity) => (
                <option key={severity || "all"} value={severity}>
                  {severity || "All severities"}
                </option>
              ))}
            </select>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {quality.isPending ? <LoadingPanel label="Loading quality issues" /> : null}
            {quality.isError ? (
              <ErrorPanel error={quality.error} onRetry={() => void quality.refetch()} />
            ) : null}
            {quality.isSuccess ? (
              quality.data.total === 0 ? (
                <NoIssuesRecorded filtered={Boolean(search.dataset || search.severity)} />
              ) : (
                <ul className="divide-y divide-border-subtle/60">
                  {quality.data.rows.map((issue) => (
                    <li key={issue.issue_id} className="px-4 py-2">
                      <QualityIssueRow issue={issue} />
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </div>
        </section>

        <section className="flex min-h-64 min-w-0 flex-col bg-surface-1">
          <header className="flex shrink-0 items-center gap-2 border-b border-border-subtle px-4 py-2">
            <h2 className="text-[13px] font-medium text-text-primary">Rights by source</h2>
            <span className="text-[11px] text-text-muted">
              declared licence terms that govern every value below them
            </span>
          </header>
          <div className="min-h-0 flex-1 overflow-auto">
            {datasets.isPending || rights.isPending ? (
              <LoadingPanel label="Loading rights" />
            ) : datasets.isError ? (
              <ErrorPanel error={datasets.error} onRetry={() => void datasets.refetch()} />
            ) : rights.isSuccess && datasets.isSuccess ? (
              <RightsMatrix datasets={datasets.data} rights={rights.data} />
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
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
          "mono text-[18px] font-medium leading-none tabular",
          tone === "warning"
            ? "text-quality-warning"
            : tone === "valid"
              ? "text-quality-valid"
              : "text-text-primary",
        )}
      >
        {value.toLocaleString("en-US")}
      </dd>
      <dt className="mt-1 text-[10px] uppercase tracking-wider text-text-muted">{label}</dt>
    </div>
  );
}

function ServingFlag({ label, value }: { label: string; value: boolean }) {
  const descriptor = value ? QUALITY_STATES.valid : QUALITY_STATES.warning;
  return (
    <span className="inline-flex items-center gap-1.5" style={{ color: descriptor.token }}>
      <span aria-hidden="true">{descriptor.glyph}</span>
      {label}: {value ? "yes" : "no"}
    </span>
  );
}

/**
 * The all-clear state.
 *
 * An empty list is the common case here and must not read as "nothing was
 * checked". It says what the absence means and what it deliberately does not.
 */
function NoIssuesRecorded({ filtered }: { filtered: boolean }) {
  return (
    <div className="p-4">
      <div className="flex items-center gap-2 rounded-control border border-quality-valid/40 bg-surface-0 px-3 py-2.5">
        <span
          aria-hidden="true"
          className="text-[14px]"
          style={{ color: QUALITY_STATES.valid.token }}
        >
          {QUALITY_STATES.valid.glyph}
        </span>
        <span className="text-[13px] text-text-secondary">
          {filtered
            ? "No rule flagged this filter"
            : "No quality rule flagged any served record"}
        </span>
      </div>
      <p className="mt-3 max-w-lg text-[12px] leading-relaxed text-text-muted">
        Quality issues are written by the validation rules that run during ingest and processing.
        An empty list means no rule flagged the scope in view — it is not a guarantee of validity,
        and it says nothing about a property no rule tests for.
      </p>
      <p className="mt-2 max-w-lg text-[12px] leading-relaxed text-text-muted">
        Quarantined records never reach the serving plane, so a value shown anywhere in this
        product has already passed the rules that were applied to it.
      </p>
    </div>
  );
}

function QualityIssueRow({ issue }: { issue: QualityIssueView }) {
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
          {issue.severity} · {issue.state}
        </span>
      </div>
      <div className="mono mt-1 grid grid-cols-2 gap-x-3 text-[10px] text-text-muted">
        <span className="truncate">{issue.dataset_id}</span>
        <span className="truncate">{issue.session_id ?? "session-wide"}</span>
        <span className="truncate">{issue.stream_id ?? "no stream scope"}</span>
        <span className="truncate">
          {issue.sample_index !== null ? `sample ${issue.sample_index}` : "no sample"}
        </span>
      </div>
    </>
  );
}

/**
 * Licence terms as a scannable matrix.
 *
 * Every column is a term a reader has to satisfy before using the data, so
 * each cell carries a shape as well as a colour and the restrictive answer is
 * the one that stands out — whichever way round the underlying flag reads.
 */
function RightsMatrix({
  datasets,
  rights,
}: {
  datasets: readonly DatasetSummary[];
  rights: RightsPage;
}) {
  const noticeFor = (policyId: string) =>
    rights.policies.find((policy) => policy.license.policy_id === policyId)?.license.notice ?? "";

  return (
    <table className="w-full text-[11px]">
      <thead className="sticky top-0 z-10 bg-surface-1">
        <tr className="text-left text-[10px] uppercase tracking-wider text-text-muted">
          <th className="px-4 py-2 font-medium">Source</th>
          <th className="px-2 py-2 font-medium">Licence</th>
          <th className="px-2 py-2 font-medium">Attribution</th>
          <th className="px-2 py-2 font-medium">Commercial</th>
          <th className="px-2 py-2 font-medium">Share-alike</th>
          <th className="px-2 py-2 font-medium">Redistribution</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border-subtle/60">
        {datasets.map((dataset) => {
          const { license } = dataset;
          return (
            <tr key={dataset.dataset_id} className="align-top">
              <td className="max-w-56 px-4 py-2">
                <span className="block truncate text-[12px] text-text-primary" title={dataset.name}>
                  {dataset.name}
                </span>
                <span
                  className="mono block truncate text-[10px] text-text-muted"
                  title={noticeFor(license.policy_id)}
                >
                  {dataset.dataset_id}
                </span>
              </td>
              <td className="px-2 py-2">
                <span className="text-text-secondary">
                  {license.identifier ?? "Unclear"}
                </span>
                {license.local_only ? (
                  <span className="mt-0.5 flex items-center gap-1 text-[10px] text-quality-warning">
                    <Scale size={9} aria-hidden="true" />
                    local-only
                  </span>
                ) : null}
              </td>
              <Term required={license.attribution_required} yes="required" no="not required" />
              <Term required={license.noncommercial_only} yes="prohibited" no="permitted" />
              <Term required={license.share_alike} yes="required" no="not required" />
              <td className="px-2 py-2">
                <span
                  className={cn(
                    "flex items-center gap-1",
                    license.redistribution === "prohibited"
                      ? "text-quality-error"
                      : "text-quality-warning",
                  )}
                >
                  <span aria-hidden="true">
                    {license.redistribution === "prohibited" ? "■" : "▲"}
                  </span>
                  {license.redistribution}
                </span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** One licence term; the restrictive answer carries the warning shape. */
function Term({ required, yes, no }: { required: boolean; yes: string; no: string }) {
  return (
    <td className="px-2 py-2">
      <span
        className={cn(
          "flex items-center gap-1",
          required ? "text-quality-warning" : "text-text-secondary",
        )}
      >
        <span aria-hidden="true">{required ? "▲" : "●"}</span>
        {required ? yes : no}
      </span>
    </td>
  );
}
