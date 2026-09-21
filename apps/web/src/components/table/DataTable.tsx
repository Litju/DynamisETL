import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type Updater,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { ReactNode } from "react";
import { useMemo, useRef, useState } from "react";

import { cn } from "@/lib/cn";

export interface DataTableColumn<T> {
  readonly id: string;
  readonly header: string;
  /** Value used for sorting only; display comes from `cell` or this value. */
  readonly accessor: (row: T) => string | number | null;
  readonly cell?: (row: T) => ReactNode;
  readonly size?: number;
  readonly align?: "left" | "right";
  readonly sortable?: boolean;
}

export interface DataTableProps<T> {
  readonly rows: readonly T[];
  readonly columns: readonly DataTableColumn<T>[];
  readonly getRowId: (row: T) => string;
  readonly onRowClick?: (row: T) => void;
  readonly selectedRowId?: string | null;
  readonly emptyState?: ReactNode;
  readonly virtualizeAbove?: number;
  readonly rowHeight?: number;
  readonly ariaLabel?: string;
}

export function shouldVirtualize(rowCount: number, threshold: number): boolean {
  return rowCount > threshold;
}

/**
 * Instrument table: TanStack Table owns the row/column/sort model, TanStack
 * Virtual owns visible indexes for long lists. Large datasets still require
 * server-side paging; virtualization is never permission to load millions of
 * rows into the browser.
 */
export function DataTable<T>({
  rows,
  columns,
  getRowId,
  onRowClick,
  selectedRowId,
  emptyState,
  virtualizeAbove = 120,
  rowHeight = 30,
  ariaLabel,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const tableColumns = useMemo<ColumnDef<T>[]>(
    () =>
      columns.map((column) => ({
        id: column.id,
        accessorFn: (row: T) => column.accessor(row),
        header: column.header,
        enableSorting: column.sortable !== false,
        sortDescFirst: false,
      })),
    [columns],
  );

  const table = useReactTable({
    data: rows as T[],
    columns: tableColumns,
    state: { sorting },
    onSortingChange: (updater: Updater<SortingState>) =>
      setSorting((current) => (typeof updater === "function" ? updater(current) : updater)),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const modelRows = table.getRowModel().rows;
  const virtualize = shouldVirtualize(modelRows.length, virtualizeAbove);
  const virtualizer = useVirtualizer({
    count: modelRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
    initialRect: { width: 900, height: 560 },
  });
  const items = virtualize
    ? measuredItems()
    : modelRows.map((_row, index) => ({
        index,
        key: index,
        start: index * rowHeight,
        size: rowHeight,
      }));

  // jsdom and pre-measurement renders report no viewport: fall back to a bounded
  // leading window so content is never blank without virtualization.
  function measuredItems() {
    const measured = virtualizer.getVirtualItems();
    if (measured.length > 0 || modelRows.length === 0) return measured;
    const fallbackCount = Math.min(
      modelRows.length,
      Math.ceil(560 / rowHeight) + 12,
    );
    return Array.from({ length: fallbackCount }, (_value, index) => ({
      index,
      key: index,
      start: index * rowHeight,
      size: rowHeight,
    }));
  }

  const template = columns
    .map((column) => `${column.size ?? 1}fr`)
    .join(" ");

  if (modelRows.length === 0) {
    return <div className="p-4">{emptyState}</div>;
  }

  const bodyHeight = virtualize ? virtualizer.getTotalSize() : modelRows.length * rowHeight;

  return (
    <div role="table" aria-label={ariaLabel} className="flex h-full min-h-0 flex-col">
      <div
        role="rowgroup"
        className="sticky top-0 z-10 shrink-0 border-b border-border-subtle bg-surface-1"
      >
        <div role="row" className="grid" style={{ gridTemplateColumns: template }}>
          {table.getHeaderGroups()[0]?.headers.map((header, index) => {
            const column = columns[index];
            const sorted = header.column.getIsSorted();
            return (
              <div
                key={header.id}
                role="columnheader"
                aria-sort={
                  sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                }
                className={cn(
                  "t-section px-2 py-1 text-text-muted",
                  column?.align === "right" && "text-right",
                )}
              >
                {header.column.getCanSort() ? (
                  <button
                    type="button"
                    onClick={header.column.getToggleSortingHandler()}
                    className="inline-flex items-center gap-1 hover:text-text-secondary"
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    <span aria-hidden="true" className="text-[9px]">
                      {sorted === "asc" ? "▲" : sorted === "desc" ? "▼" : "·"}
                    </span>
                  </button>
                ) : (
                  flexRender(header.column.columnDef.header, header.getContext())
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div
        role="rowgroup"
        ref={scrollRef}
        // Scrollable regions must be reachable by keyboard (WCAG 2.2 / axe
        // scrollable-region-focusable); arrow keys scroll while a cell keeps
        // focus for row activation.
        tabIndex={0}
        aria-label={ariaLabel ? `${ariaLabel} rows` : "Table rows"}
        className="min-h-0 flex-1 overflow-auto"
      >
        <div role="presentation" className="relative" style={{ height: bodyHeight }}>
          {items.map((item) => {
            const row = modelRows[item.index];
            if (!row) return null;
            const rowId = getRowId(row.original);
            return (
              <div
                key={rowId}
                role="row"
                tabIndex={onRowClick ? 0 : -1}
                aria-selected={selectedRowId === rowId}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onRowClick(row.original);
                        }
                      }
                    : undefined
                }
                className={cn(
                  // Rows are absolutely positioned at index * rowHeight, so
                  // content taller than the row would bleed into its
                  // neighbour. Clipping keeps a two-line cell readable and the
                  // row rhythm exact.
                  "absolute left-0 top-0 grid w-full overflow-hidden border-b border-border-subtle/60",
                  onRowClick &&
                    "cursor-pointer hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none",
                  selectedRowId === rowId &&
                    "bg-surface-3 shadow-[inset_2px_0_0_0_var(--d-accent)]",
                )}
                style={{
                  gridTemplateColumns: template,
                  height: item.size,
                  transform: `translateY(${item.start}px)`,
                }}
              >
                {row.getVisibleCells().map((cell, index) => {
                  const column = columns[index];
                  return (
                    <div
                      key={cell.id}
                      role="cell"
                      className={cn(
                        "flex min-w-0 items-center px-2 text-[12px]",
                        column?.align === "right" && "justify-end text-right",
                      )}
                    >
                      {column?.cell
                        ? column.cell(row.original)
                        : String(cell.getValue() ?? "—")}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
