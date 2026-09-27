import type { UseQueryResult } from "@tanstack/react-query";
import { useMemo } from "react";

import type { SeasonMetricView, SeasonRowPage, SeasonRowView } from "@/api/types";
import { ErrorPanel, LoadingPanel } from "@/components/common/StatePanel";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { formatSeasonValue, shortTeamName, unitSuffix } from "@/lib/season-model";

function keyOf(row: SeasonRowView): string {
  return `${row.subject_id}|${row.team_id}|${row.position_group}`;
}

/** Sortable, virtualized population table over exactly the ranking population. */
export function SeasonPopulationTable({
  registry,
  selected,
  query,
  selectedKey,
  populationLabel,
  onSelect,
}: {
  registry: readonly SeasonMetricView[];
  selected: readonly string[];
  query: UseQueryResult<SeasonRowPage>;
  selectedKey: string | null;
  populationLabel: string;
  onSelect: (row: SeasonRowView) => void;
}) {
  const byColumn = useMemo(() => new Map(registry.map((metric) => [metric.column, metric])), [registry]);
  const columns = useMemo<DataTableColumn<SeasonRowView>[]>(
    () => [
      {
        id: "player",
        header: "Player",
        accessor: (row) => row.player_name,
        cell: (row) => <span className="text-text-primary">{row.player_name}</span>,
        size: 180,
      },
      { id: "team", header: "Team", accessor: (row) => shortTeamName(row.team_name), size: 150 },
      { id: "position", header: "Position", accessor: (row) => row.position_group, size: 120 },
      {
        id: "matches",
        header: "Matches",
        accessor: (row) => row.matches,
        align: "right",
        size: 72,
        cell: (row) => <span className="mono">{row.matches ?? "—"}</span>,
      },
      ...selected.map<DataTableColumn<SeasonRowView>>((column) => {
        const metric = byColumn.get(column);
        const unit = metric?.unit ?? "";
        const suffix = unitSuffix(unit);
        return {
          id: column,
          header: `${metric?.label ?? column}${suffix ? ` (${suffix})` : ""}`,
          accessor: (row) => row.values[column] ?? null,
          align: "right",
          size: 132,
          cell: (row) => <span className="mono">{formatSeasonValue(row.values[column], unit)}</span>,
        };
      }),
    ],
    [byColumn, selected],
  );

  if (query.isPending) return <LoadingPanel label="Loading population rows" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-baseline justify-between gap-3 px-6 pb-2 pt-4">
        <h2 className="t-section">Population table</h2>
        <span className="t-label">
          {populationLabel} · <span className="mono">{query.data.total}</span> rows · sort any column
        </span>
      </div>
      <div className="min-h-0 flex-1 px-4 pb-4">
        <DataTable
          rows={query.data.rows}
          columns={columns}
          getRowId={keyOf}
          onRowClick={onSelect}
          selectedRowId={selectedKey}
          ariaLabel={`Season rows of ${populationLabel}`}
          virtualizeAbove={60}
        />
      </div>
    </div>
  );
}
