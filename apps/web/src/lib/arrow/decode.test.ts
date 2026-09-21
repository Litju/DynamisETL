import { tableFromArrays, tableToIPC } from "apache-arrow";
import { describe, expect, it } from "vitest";

import { decodeWindow, pointsForColumn } from "@/lib/arrow/decode";

function arrowBuffer(): ArrayBuffer {
  const table = tableFromArrays({
    t_rel_ns: BigInt64Array.from([0n, 40_000_000n, 80_000_000n]),
    sample_index: BigInt64Array.from([0n, 1n, 2n]),
    subject_id: ["s1", "s1", "s1"],
    x_m: Float64Array.from([0, 1.5, Number.NaN]),
    is_available: [true, true, false],
  });
  const ipc = tableToIPC(table, "stream");
  return ipc.buffer.slice(ipc.byteOffset, ipc.byteOffset + ipc.byteLength) as ArrayBuffer;
}

describe("Arrow IPC decode", () => {
  it("decodes columnar typed arrays without row objects", () => {
    const decoded = decodeWindow(arrowBuffer());
    expect(decoded.rowCount).toBe(3);
    expect(Array.from(decoded.timeNs)).toEqual([0n, 40_000_000n, 80_000_000n]);
    const x = decoded.columns.find((column) => column.name === "x_m");
    expect(x?.numeric).toBe(true);
    expect(Array.from(x?.values as Float64Array)).toEqual([0, 1.5, Number.NaN]);
    const subject = decoded.columns.find((column) => column.name === "subject_id");
    expect(subject?.numeric).toBe(false);
    expect(subject?.values).toEqual(["s1", "s1", "s1"]);
    // Booleans are non-numeric columns; the reducer renders them as keys.
    const available = decoded.columns.find((column) => column.name === "is_available");
    expect(available?.numeric).toBe(false);
    const sampleIndex = decoded.columns.find((column) => column.name === "sample_index");
    expect(Array.from(sampleIndex?.values as Float64Array)).toEqual([0, 1, 2]);
  });

  it("shapes renderer points relative to an origin without interpolating nulls", () => {
    const decoded = decodeWindow(arrowBuffer());
    const points = pointsForColumn(decoded, "x_m", 0n);
    expect(points).toBeInstanceOf(Float64Array);
    expect(points.length).toBe(6);
    expect(points[0]).toBe(0);
    expect(points[1]).toBe(0);
    expect(points[2]).toBe(40);
    expect(points[3]).toBe(1.5);
    expect(points[4]).toBe(80);
    expect(Number.isNaN(points[5] ?? 0)).toBe(true);
    const missing = pointsForColumn(decoded, "not_a_column", 0n);
    expect(missing.length).toBe(0);
  });
});
