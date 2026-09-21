/**
 * Arrow IPC decode kernels.
 *
 * Pure functions shared by the Web Worker and unit tests: an Arrow IPC stream is
 * parsed once into columnar typed arrays, and renderer-ready point vectors are
 * shaped without ever materializing one generic object per row.
 */

import { tableFromIPC, type Table } from "apache-arrow";

export interface ArrowColumn {
  readonly name: string;
  readonly type: string;
  readonly numeric: boolean;
  readonly values: Float64Array | string[];
}

export interface DecodedWindow {
  readonly rowCount: number;
  readonly columns: readonly ArrowColumn[];
  /** Canonical time in nanoseconds, exact for the full int64 range. */
  readonly timeNs: BigInt64Array<ArrayBufferLike>;
}

const TIME_COLUMN = "t_rel_ns";

export function decodeWindow(buffer: ArrayBuffer | Uint8Array): DecodedWindow {
  const table: Table = tableFromIPC(buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer));
  const columns: ArrowColumn[] = [];
  let timeNs: BigInt64Array<ArrayBufferLike> = new BigInt64Array(0);
  table.schema.fields.forEach((field, index) => {
    const vector = table.getChildAt(index);
    if (vector === null) return;
    if (field.name === TIME_COLUMN) {
      timeNs = toBigInt64(vector);
      return;
    }
    if (isNumericType(field.type.toString())) {
      columns.push({
        name: field.name,
        type: field.type.toString(),
        numeric: true,
        values: toFloat64(vector),
      });
      return;
    }
    columns.push({
      name: field.name,
      type: field.type.toString(),
      numeric: false,
      values: toStringArray(vector),
    });
  });
  return { rowCount: table.numRows, columns, timeNs };
}

function isNumericType(typeName: string): boolean {
  return /^(Int|Uint|Float|Decimal)/.test(typeName);
}

function toFloat64(vector: {
  readonly length: number;
  get(index: number): unknown;
}): Float64Array {
  const output = new Float64Array(vector.length);
  for (let index = 0; index < vector.length; index += 1) {
    const value = vector.get(index);
    output[index] = typeof value === "number" ? value : Number.NaN;
  }
  return output;
}

function toBigInt64(vector: {
  readonly length: number;
  get(index: number): unknown;
}): BigInt64Array {
  const output = new BigInt64Array(vector.length);
  for (let index = 0; index < vector.length; index += 1) {
    const value = vector.get(index);
    if (typeof value === "bigint") output[index] = value;
    else if (typeof value === "number" && Number.isFinite(value)) output[index] = BigInt(Math.trunc(value));
  }
  return output;
}

function toStringArray(vector: {
  readonly length: number;
  get(index: number): unknown;
}): string[] {
  const output: string[] = [];
  for (let index = 0; index < vector.length; index += 1) {
    const value = vector.get(index);
    output.push(value === null || value === undefined ? "" : String(value));
  }
  return output;
}

/**
 * Shape a measure as interleaved [xMs, value] Float64Array for the renderer.
 * Nulls become NaN bands, never interpolated values.
 */
export function pointsForColumn(
  decoded: DecodedWindow,
  columnName: string,
  originNs: bigint,
): Float64Array {
  const column = decoded.columns.find((candidate) => candidate.name === columnName);
  if (!column || !column.numeric) return new Float64Array(0);
  const output = new Float64Array(decoded.timeNs.length * 2);
  const values = column.values as Float64Array;
  for (let index = 0; index < decoded.timeNs.length; index += 1) {
    const tNs = decoded.timeNs[index] ?? 0n;
    const xMs = Number(tNs - originNs) / 1e6;
    output[index * 2] = xMs;
    const value = values[index];
    output[index * 2 + 1] = typeof value === "number" ? value : Number.NaN;
  }
  return output;
}
