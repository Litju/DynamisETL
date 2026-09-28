/**
 * Instrument chart palette.
 *
 * ECharts renders to canvas and cannot resolve CSS custom properties, so the
 * semantic tokens are read from the document once per option build and passed
 * explicitly. Fallback values keep the module usable in tests and SSR.
 */

export interface ChartPalette {
  readonly grid: string;
  readonly axis: string;
  readonly reference: string;
  readonly playhead: string;
  readonly brush: string;
  readonly surface: string;
  readonly text: string;
  readonly textMuted: string;
  readonly border: string;
  readonly measurement: Record<string, string>;
  readonly warning: string;
  readonly error: string;
  readonly series: readonly string[];
}

const FALLBACK: ChartPalette = {
  grid: "oklch(0.31 0.01 255)",
  axis: "oklch(0.62 0.012 255)",
  reference: "oklch(0.5 0.012 255)",
  playhead: "oklch(0.82 0.13 200)",
  brush: "oklch(0.74 0.13 215 / 0.16)",
  surface: "oklch(0.17 0.012 255)",
  text: "oklch(0.93 0.005 255)",
  textMuted: "oklch(0.6 0.012 255)",
  border: "oklch(0.3 0.012 255)",
  measurement: {
    RAW_MEASURED: "oklch(0.78 0.12 205)",
    SOURCE_DERIVED: "oklch(0.8 0.14 80)",
    PIPELINE_DERIVED: "oklch(0.74 0.15 290)",
    MODEL_ESTIMATED: "oklch(0.74 0.16 350)",
  },
  warning: "oklch(0.81 0.14 80)",
  error: "oklch(0.68 0.19 25)",
  series: [
    "oklch(0.78 0.12 205)",
    "oklch(0.8 0.14 80)",
    "oklch(0.74 0.15 290)",
    "oklch(0.74 0.16 350)",
    "oklch(0.75 0.15 45)",
    "oklch(0.75 0.13 175)",
    "oklch(0.76 0.12 140)",
    "oklch(0.76 0.12 245)",
  ],
};

export const MEASUREMENT_COLOR_TOKEN: Record<string, string> = {
  RAW_MEASURED: "--d-measurement-raw",
  SOURCE_DERIVED: "--d-measurement-source-derived",
  PIPELINE_DERIVED: "--d-measurement-pipeline-derived",
  MODEL_ESTIMATED: "--d-measurement-model-estimated",
};

function readVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = styles.getPropertyValue(name).trim();
  return value.length > 0 ? value : fallback;
}

export function readPalette(root?: HTMLElement | null): ChartPalette {
  const element = root ?? (typeof document !== "undefined" ? document.documentElement : null);
  if (!element || typeof getComputedStyle !== "function") {
    return FALLBACK;
  }
  const styles = getComputedStyle(element);
  const measurement: Record<string, string> = {};
  for (const [key, token] of Object.entries(MEASUREMENT_COLOR_TOKEN)) {
    measurement[key] = readVar(styles, token, FALLBACK.measurement[key] ?? FALLBACK.series[0]!);
  }
  return {
    grid: readVar(styles, "--d-chart-grid", FALLBACK.grid),
    axis: readVar(styles, "--d-chart-axis", FALLBACK.axis),
    reference: readVar(styles, "--d-chart-reference", FALLBACK.reference),
    playhead: readVar(styles, "--d-playhead", FALLBACK.playhead),
    brush: readVar(styles, "--d-brush", FALLBACK.brush),
    surface: readVar(styles, "--d-surface-1", FALLBACK.surface),
    text: readVar(styles, "--d-text-primary", FALLBACK.text),
    textMuted: readVar(styles, "--d-text-muted", FALLBACK.textMuted),
    border: readVar(styles, "--d-border-subtle", FALLBACK.border),
    measurement,
    warning: readVar(styles, "--d-quality-warning", FALLBACK.warning),
    error: readVar(styles, "--d-quality-error", FALLBACK.error),
    series: FALLBACK.series,
  };
}

/**
 * The Dynamis ECharts theme: library defaults never ship. Typography is the
 * instrument's (Inter for language, JetBrains Mono for values), grids are
 * hairlines, tooltips are L2 overlays and the colour cycle is the semantic
 * series palette. Charts still set their own analytical encodings on top.
 */
export function dynamisChartTheme(palette: ChartPalette, root?: HTMLElement | null): Record<string, unknown> {
  const element = root ?? (typeof document !== "undefined" ? document.documentElement : null);
  const styles = element && typeof getComputedStyle === "function" ? getComputedStyle(element) : null;
  const sans = styles?.getPropertyValue("--font-sans").trim() || "Inter Variable, system-ui, sans-serif";
  const mono = styles?.getPropertyValue("--font-mono").trim() || "JetBrains Mono Variable, monospace";
  const overlay = styles?.getPropertyValue("--d-surface-2").trim() || palette.surface;
  const axis = {
    axisLine: { lineStyle: { color: palette.border } },
    axisTick: { show: false },
    axisLabel: { color: palette.textMuted, fontFamily: mono, fontSize: 10 },
    splitLine: { lineStyle: { color: palette.grid, width: 1 } },
    nameTextStyle: { color: palette.textMuted, fontFamily: sans, fontSize: 11 },
  };
  return {
    color: palette.series,
    backgroundColor: "transparent",
    textStyle: { fontFamily: sans, color: palette.text },
    title: { textStyle: { fontFamily: sans, fontWeight: 600, color: palette.text } },
    legend: { textStyle: { fontFamily: sans, color: palette.textMuted, fontSize: 11 }, icon: "roundRect", itemWidth: 10, itemHeight: 3 },
    tooltip: {
      backgroundColor: overlay,
      borderColor: palette.border,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { fontFamily: sans, color: palette.text, fontSize: 11.5 },
      extraCssText: "border-radius:8px;box-shadow:var(--d-shadow-overlay);",
      axisPointer: { lineStyle: { color: palette.playhead, width: 1 }, crossStyle: { color: palette.reference } },
    },
    categoryAxis: axis,
    valueAxis: axis,
    timeAxis: axis,
    logAxis: axis,
    dataZoom: {
      borderColor: palette.border,
      fillerColor: palette.brush,
      handleStyle: { color: palette.playhead, borderColor: palette.playhead },
      textStyle: { color: palette.textMuted, fontFamily: mono },
    },
  };
}

export function seriesColor(
  palette: ChartPalette,
  measurementClass: string | null | undefined,
  index = 0,
): string {
  if (measurementClass && palette.measurement[measurementClass]) {
    return palette.measurement[measurementClass]!;
  }
  return palette.series[index % palette.series.length]!;
}
