import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";

import { MeasurementClassBadge } from "@/components/common/Badges";
import { EChart } from "@/components/charts/EChart";
import {
  differenceOption,
  distributionOption,
  pairedScatterOption,
} from "@/components/charts/compare-options";
import { MetricPicker } from "@/components/common/MetricPicker";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { MetricCatalogEntry, MetricValue } from "@/api/types";
import { metricDefinitionsQuery, metricsQuery } from "@/lib/api/queries";
import { readPalette } from "@/lib/chart-palette";
import { cn } from "@/lib/cn";
import {
  differenceSummary,
  fiveNumber,
  groupValues,
  GROUP_BY_LABELS,
  pairMetrics,
  PAIRING_BASIS,
  type GroupBy,
} from "@/lib/compare-model";
import { formatMetricValue, INTERCHANGEABILITY_NOTE } from "@/lib/measurement";
import { compareSearchSchema, parseSearch } from "@/lib/search";
import type { CompareSearch } from "@/lib/search";

const COMPARE_PAGE_LIMIT = 1000;
const GROUP_OPTIONS: readonly GroupBy[] = [
  "dataset_id",
  "session_id",
  "subject_id",
  "trial_id",
];

export function defineCompareRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/compare",
    validateSearch: (search: Record<string, unknown>) => parseSearch(compareSearchSchema, search),
    component: ComparePage,
  });
}

/**
 * Compare: visual analysis of served values.
 *
 * One metric gives a distribution comparison across groups. Two metrics give a
 * paired comparison — but only where the rows genuinely pair on the same
 * observation, and only with a difference view when they share an SI unit.
 * Identity boundaries are never crossed: rows from different datasets do not
 * pair, because nothing links a subject in one source to a subject in another.
 */
export function ComparePage() {
  const search = useSearch({ from: "/compare" });
  const navigate = useNavigate();
  const definitions = useQuery(metricDefinitionsQuery());

  const update = (patch: Partial<CompareSearch>) => {
    void navigate({
      to: "/compare",
      search: (previous: Record<string, unknown>) => ({ ...previous, ...patch }),
      replace: true,
    });
  };

  const served = useMemo(
    () => (definitions.data ?? []).filter((entry) => entry.value_count > 0),
    [definitions.data],
  );
  const metricA = search.metric ?? null;
  const metricB = search.b ?? null;
  const groupBy =
    typeof search.a === "string" && GROUP_OPTIONS.includes(search.a as GroupBy)
      ? (search.a as GroupBy)
      : "dataset_id";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-3">
        <h1 className="t-surface-title">
          Compare served values
        </h1>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <MetricPicker
            label="Metric"
            value={metricA}
            options={served}
            isPending={definitions.isPending}
            onChange={(metricId) => update({ metric: metricId ?? undefined })}
          />
          <MetricPicker
            label="Compare with (optional)"
            value={metricB}
            options={served}
            isPending={definitions.isPending}
            allowEmpty
            onChange={(metricId) => update({ b: metricId ?? undefined })}
          />
          {metricB === null ? (
            <label className="flex flex-col gap-1 text-[11px] text-text-muted">
              Group by
              <select
                value={groupBy}
                onChange={(event) => update({ a: event.target.value })}
                className="h-7 rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[12px] text-text-secondary outline-none focus:border-accent"
              >
                {GROUP_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {GROUP_BY_LABELS[option]}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </header>

      {definitions.isError ? (
        <ErrorPanel error={definitions.error} onRetry={() => void definitions.refetch()} />
      ) : metricA === null ? (
        <StatePanel
          state="empty"
          title="Choose a metric to compare."
          detail="Distributions are compared across datasets, sessions, subjects or trials. Adding a second metric compares the two on the same observation, where the rows genuinely pair."
        />
      ) : (
        <CompareBody
          metricA={metricA}
          metricB={metricB}
          groupBy={groupBy}
          definitions={served}
        />
      )}
    </div>
  );
}

function CompareBody({
  metricA,
  metricB,
  groupBy,
  definitions,
}: {
  metricA: string;
  metricB: string | null;
  groupBy: GroupBy;
  definitions: readonly MetricCatalogEntry[];
}) {
  const palette = useMemo(() => readPalette(), []);
  const queryA = useQuery(metricsQuery({ metricId: metricA, limit: COMPARE_PAGE_LIMIT }));
  const queryB = useQuery({
    ...metricsQuery({ metricId: metricB ?? "", limit: COMPARE_PAGE_LIMIT }),
    enabled: metricB !== null,
  });

  const defA = definitions.find((entry) => entry.metric_id === metricA) ?? null;
  const defB = definitions.find((entry) => entry.metric_id === metricB) ?? null;

  if (queryA.isPending || (metricB !== null && queryB.isPending)) {
    return <LoadingPanel label="Loading served values" />;
  }
  if (queryA.isError) {
    return <ErrorPanel error={queryA.error} onRetry={() => void queryA.refetch()} />;
  }
  if (queryB.isError) {
    return <ErrorPanel error={queryB.error} onRetry={() => void queryB.refetch()} />;
  }

  const rowsA = queryA.data.rows;
  const rowsB = queryB.data?.rows ?? [];
  if (rowsA.length === 0) {
    return (
      <StatePanel
        state="empty"
        title="No current value serves this metric."
        detail="The metric is registered but the Gold mart holds no value for it yet."
      />
    );
  }

  return metricB === null ? (
    <UnpairedComparison
      rows={rowsA}
      metricA={metricA}
      groupBy={groupBy}
      label={defA?.name ?? metricA}
      unit={defA?.si_unit ?? rowsA[0]!.si_unit}
      measurementClass={defA?.measurement_class ?? rowsA[0]!.measurement_class}
      palette={palette}
      total={queryA.data.total}
    />
  ) : (
    <PairedComparison
      rows={[...rowsA, ...rowsB]}
      metricA={metricA}
      metricB={metricB}
      labelA={defA?.name ?? metricA}
      labelB={defB?.name ?? metricB}
      palette={palette}
    />
  );
}

function UnpairedComparison({
  rows,
  metricA,
  groupBy,
  label,
  unit,
  measurementClass,
  palette,
  total,
}: {
  rows: readonly MetricValue[];
  metricA: string;
  groupBy: GroupBy;
  label: string;
  unit: string;
  measurementClass: string;
  palette: ReturnType<typeof readPalette>;
  total: number;
}) {
  const groups = useMemo(() => groupValues(rows, metricA, groupBy), [groupBy, metricA, rows]);

  if (groups.length === 0) {
    return (
      <StatePanel
        state="empty"
        title={`No served value names a ${GROUP_BY_LABELS[groupBy].toLowerCase()}.`}
        detail="Group by another identity field to compare these values."
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <section className="flex min-h-0 flex-1 flex-col bg-surface-1">
        <header className="flex shrink-0 flex-wrap items-baseline justify-between gap-2 border-b border-border-subtle px-4 py-2">
          <h2 className="t-analysis-title">
            {label}
            {unit !== "1" ? (
              <span className="ml-1.5 text-[11px] font-normal text-text-muted">[{unit}]</span>
            ) : null}
            <span className="ml-2 text-[11px] font-normal text-text-muted">
              by {GROUP_BY_LABELS[groupBy].toLowerCase()}
            </span>
          </h2>
          <span className="flex items-center gap-2 text-[10px] text-text-muted">
            {groups.length} groups · {total.toLocaleString("en-US")} served values
            <MeasurementClassBadge measurementClass={measurementClass} compact />
          </span>
        </header>
        <div className="min-h-0 flex-1">
          <EChart
            ariaLabel={`Distribution of ${label} by ${GROUP_BY_LABELS[groupBy]}`}
            option={distributionOption(groups, unit, measurementClass, palette)}
          />
        </div>
        <p className="shrink-0 border-t border-border-subtle px-4 py-1.5 text-[10px] leading-relaxed text-text-muted">
          Box and whiskers describe the served values in view — minimum, quartiles, median,
          maximum. They are a description of this selection, not a pipeline result, and groups
          are compared only as distributions: no observation is paired across groups.
        </p>
      </section>
      <GroupEvidence groups={groups} unit={unit} />
    </div>
  );
}

function GroupEvidence({
  groups,
  unit,
}: {
  groups: ReturnType<typeof groupValues>;
  unit: string;
}) {
  const summaries = groups.map((group) => ({ group, summary: fiveNumber(group.values) }));
  const show = (value: number) => formatMetricValue(value, unit).text;
  return (
    <section className="shrink-0 border-t border-border-subtle bg-surface-1">
      <h3 className="t-section px-4 pt-2 text-text-muted">
        Group summary
      </h3>
      <div className="max-h-48 overflow-y-auto px-4 pb-3 pt-1">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="t-section text-left text-text-muted">
              <th className="py-1 font-medium">Group</th>
              <th className="py-1 text-right font-medium">n</th>
              <th className="py-1 text-right font-medium">Min</th>
              <th className="py-1 text-right font-medium">Median</th>
              <th className="py-1 text-right font-medium">Max</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle/60">
            {summaries.map(({ group, summary }) =>
              summary === null ? null : (
                <tr key={group.groupId}>
                  <td className="mono max-w-64 truncate py-1 text-text-secondary" title={group.groupId}>
                    {group.groupId}
                  </td>
                  <td className="mono py-1 text-right tabular text-text-muted">{summary.count}</td>
                  <td className="mono py-1 text-right tabular">{show(summary.min)}</td>
                  <td className="mono py-1 text-right tabular text-text-primary">
                    {show(summary.median)}
                  </td>
                  <td className="mono py-1 text-right tabular">{show(summary.max)}</td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PairedComparison({
  rows,
  metricA,
  metricB,
  labelA,
  labelB,
  palette,
}: {
  rows: readonly MetricValue[];
  metricA: string;
  metricB: string;
  labelA: string;
  labelB: string;
  palette: ReturnType<typeof readPalette>;
}) {
  const pairing = useMemo(() => pairMetrics(rows, metricA, metricB), [metricA, metricB, rows]);
  const difference = useMemo(
    () => (pairing.sameUnit ? differenceSummary(pairing.pairs) : null),
    [pairing],
  );

  if (pairing.pairs.length === 0) {
    return (
      <StatePanel
        state="unavailable"
        title="These metrics do not pair."
        detail={`A pair requires the same ${PAIRING_BASIS}. No observation carries both metrics, so plotting them against each other would assert a relationship the data does not contain.`}
      />
    );
  }

  const unit = pairing.unitA;
  const labels = { a: labelA, b: labelB, unit };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border-subtle bg-surface-0 px-4 py-1.5 text-[11px]">
        <span className="inline-flex items-center gap-1.5 rounded-[3px] border border-quality-valid px-1.5 py-px text-quality-valid">
          <span aria-hidden="true">●</span>
          {pairing.pairs.length} paired observations
        </span>
        <span className="text-text-muted">paired on {PAIRING_BASIS}</span>
        {pairing.unmatchedA + pairing.unmatchedB > 0 ? (
          <span className="text-text-muted">
            {pairing.unmatchedA + pairing.unmatchedB} unpaired values excluded
          </span>
        ) : null}
        {!pairing.sameUnit ? (
          <span className="inline-flex items-center gap-1.5 text-quality-warning">
            <span aria-hidden="true">▲</span>
            Different units ({pairing.unitA} vs {pairing.unitB}); no difference view
          </span>
        ) : null}
        <span className="ml-auto text-text-muted">{INTERCHANGEABILITY_NOTE}</span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-border-subtle xl:grid-cols-2">
        <ChartPane
          title="Paired observations"
          note="each point is one observation; the dashed line is exact agreement"
        >
          <EChart
            ariaLabel={`${labelA} against ${labelB} for each paired observation`}
            option={pairedScatterOption(pairing.pairs, labels, palette)}
          />
        </ChartPane>
        {difference ? (
          <ChartPane
            title={difference.proportionalBias ? "Difference against magnitude" : "Difference against mean"}
            note={
              difference.proportionalBias
                ? "magnitude-dependent bias detected; agreement limits withheld"
                : "limits describe the spread of the plotted differences"
            }
          >
            <EChart
              ariaLabel={`Difference between ${labelB} and ${labelA} against their mean`}
              option={differenceOption(difference, labels, palette)}
            />
          </ChartPane>
        ) : (
          <ChartPane
            title="Difference against mean"
            note="unavailable for metrics with different units"
          >
            <StatePanel
              state="unavailable"
              title="A difference needs one unit."
              detail={`${labelA} is in ${pairing.unitA} and ${labelB} is in ${pairing.unitB}; subtracting them would produce a quantity with no meaning.`}
            />
          </ChartPane>
        )}
      </div>

      <PairEvidence
        pairs={pairing.pairs}
        labelA={labelA}
        labelB={labelB}
        unit={unit}
        sameUnit={pairing.sameUnit}
      />
    </div>
  );
}

function ChartPane({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex min-h-64 min-w-0 flex-col bg-surface-1">
      <header className="flex shrink-0 flex-wrap items-baseline justify-between gap-2 border-b border-border-subtle px-3 py-2">
        <h2 className="t-analysis-title">{title}</h2>
        <span className="text-[10px] text-text-muted">{note}</span>
      </header>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}

function PairEvidence({
  pairs,
  labelA,
  labelB,
  unit,
  sameUnit,
}: {
  pairs: ReturnType<typeof pairMetrics>["pairs"];
  labelA: string;
  labelB: string;
  unit: string;
  sameUnit: boolean;
}) {
  const columns: DataTableColumn<(typeof pairs)[number]>[] = [
    {
      id: "entity",
      header: "Observation",
      size: 2,
      accessor: (pair) => pair.label,
      cell: (pair) => (
        <span className="mono truncate text-[11px] text-text-secondary" title={pair.label}>
          {pair.label}
        </span>
      ),
    },
    {
      id: "a",
      header: labelA,
      size: 1.4,
      align: "right",
      accessor: (pair) => pair.a,
      cell: (pair) => (
        <span className="mono tabular text-[11px]" title={`Exact value: ${pair.a}`}>
          {formatMetricValue(pair.a, unit).text}
        </span>
      ),
    },
    {
      id: "b",
      header: labelB,
      size: 1.4,
      align: "right",
      accessor: (pair) => pair.b,
      cell: (pair) => (
        <span className="mono tabular text-[11px]" title={`Exact value: ${pair.b}`}>
          {formatMetricValue(pair.b, unit).text}
        </span>
      ),
    },
    {
      id: "difference",
      header: "Difference",
      size: 1.2,
      align: "right",
      accessor: (pair) => pair.b - pair.a,
      cell: (pair) =>
        sameUnit ? (
          <span
            className={cn(
              "mono tabular text-[11px]",
              pair.b - pair.a >= 0 ? "text-text-primary" : "text-text-muted",
            )}
          >
            {formatMetricValue(pair.b - pair.a, unit).text}
          </span>
        ) : (
          <span className="text-[11px] text-text-muted">—</span>
        ),
    },
  ];

  return (
    <section className="h-56 shrink-0 border-t border-border-subtle bg-surface-1">
      <header className="flex items-center gap-2 border-b border-border-subtle px-4 py-1.5">
        <h3 className="t-section text-text-muted">
          Paired evidence
        </h3>
        <span className="text-[10px] text-text-muted">
          drill-down for the plotted pairs; exact values on hover
        </span>
      </header>
      <div className="h-[calc(100%-2rem)]">
        <DataTable
          ariaLabel="Paired observations"
          rows={pairs}
          columns={columns}
          rowHeight={28}
          getRowId={(pair) => pair.key}
          emptyState={<StatePanel state="empty" title="No pair to show." />}
        />
      </div>
    </section>
  );
}
