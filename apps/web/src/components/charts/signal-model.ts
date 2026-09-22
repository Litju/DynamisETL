export interface SignalSeries {
  readonly name: string;
  readonly unit: string;
  readonly measurementClass: string | null | undefined;
  readonly paneIndex: number;
  readonly points: ReadonlyArray<readonly [number, number | null]>;
}

export interface SignalBand {
  readonly name: string;
  readonly unit: string;
  readonly measurementClass: string | null | undefined;
  readonly paneIndex: number;
  readonly base: string;
  readonly points: ReadonlyArray<readonly [number, number | null, number | null]>;
}

export interface SignalPane {
  readonly id: string;
  readonly label: string;
  readonly unit: string;
}

export function formatSignalValue(value: number, unit: string): string {
  if (!Number.isFinite(value)) return "unavailable";
  const magnitude = Math.abs(value);
  const digits = magnitude >= 100 ? 1 : magnitude >= 1 ? 2 : 4;
  const text = value.toFixed(digits).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
  return unit === "1" ? text : `${text} ${unit}`;
}

export function reductionNote(meta: {
  readonly reduction: {
    readonly method: string;
    readonly source_points: number;
    readonly returned_points: number;
  } | null;
}): string | null {
  if (!meta.reduction) return null;
  return `Display-reduced: ${meta.reduction.method}, ${meta.reduction.source_points} source points → ${meta.reduction.returned_points} envelope points; metrics never derive from this view.`;
}
