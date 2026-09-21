import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DataTable, shouldVirtualize, type DataTableColumn } from "@/components/table/DataTable";
import { StatePanel } from "@/components/common/StatePanel";

interface Row {
  readonly id: string;
  readonly name: string;
  readonly value: number;
}

const ROWS: Row[] = [
  { id: "b", name: "Bravo", value: 2 },
  { id: "a", name: "Alpha", value: 3 },
  { id: "c", name: "Charlie", value: 1 },
];

const COLUMNS: DataTableColumn<Row>[] = [
  { id: "name", header: "Name", accessor: (row) => row.name, size: 2 },
  {
    id: "value",
    header: "Value",
    accessor: (row) => row.value,
    align: "right",
    size: 1,
  },
];

describe("instrument table", () => {
  it("renders accessible roles and sorts on header activation", async () => {
    const user = userEvent.setup();
    render(
      <DataTable ariaLabel="Test rows" rows={ROWS} columns={COLUMNS} getRowId={(row) => row.id} />,
    );
    expect(screen.getByRole("table", { name: "Test rows" })).toBeInTheDocument();
    const rendered = screen.getAllByRole("row").slice(1);
    expect(rendered.map((row) => row.textContent)).toEqual(["Bravo2", "Alpha3", "Charlie1"]);

    await user.click(screen.getByRole("button", { name: /Name/ }));
    const ascending = screen.getAllByRole("row").slice(1);
    expect(ascending.map((row) => row.textContent)).toEqual(["Alpha3", "Bravo2", "Charlie1"]);
    expect(screen.getByRole("columnheader", { name: /Name/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );

    await user.click(screen.getByRole("button", { name: /Name/ }));
    const descending = screen.getAllByRole("row").slice(1);
    expect(descending.map((row) => row.textContent)).toEqual(["Charlie1", "Bravo2", "Alpha3"]);
  });

  it("sorts numerically for measure columns", async () => {
    const user = userEvent.setup();
    render(
      <DataTable rows={ROWS} columns={COLUMNS} getRowId={(row) => row.id} />,
    );
    await user.click(screen.getByRole("button", { name: /Value/ }));
    const rendered = screen.getAllByRole("row").slice(1);
    expect(rendered.map((row) => row.textContent)).toEqual(["Charlie1", "Bravo2", "Alpha3"]);
  });

  it("selects a row by click and by keyboard", async () => {
    const user = userEvent.setup();
    const onRowClick = vi.fn();
    render(
      <DataTable
        rows={ROWS}
        columns={COLUMNS}
        getRowId={(row) => row.id}
        onRowClick={onRowClick}
        selectedRowId="a"
      />,
    );
    const selected = screen.getAllByRole("row").find((row) => row.getAttribute("aria-selected") === "true");
    expect(selected?.textContent).toContain("Alpha");
    await user.click(screen.getByText("Bravo"));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
    screen.getAllByRole("row")[1]?.focus();
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledTimes(2);
  });

  it("renders an explicit empty state and virtualization threshold", () => {
    render(
      <DataTable
        rows={[]}
        columns={COLUMNS}
        getRowId={(row) => row.id}
        emptyState={<StatePanel state="empty" title="Nothing here." />}
      />,
    );
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
    expect(shouldVirtualize(120, 120)).toBe(false);
    expect(shouldVirtualize(121, 120)).toBe(true);
  });

  it("renders only the visible window above the virtualization threshold", () => {
    const many: Row[] = Array.from({ length: 400 }, (_value, index) => ({
      id: `row-${index}`,
      name: `Row ${index}`,
      value: index,
    }));
    render(
      <DataTable
        rows={many}
        columns={COLUMNS}
        getRowId={(row) => row.id}
        virtualizeAbove={50}
        rowHeight={30}
      />,
    );
    const rendered = screen.getAllByRole("row").length - 1;
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(60);
  });
});
