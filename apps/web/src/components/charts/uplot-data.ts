import type uPlot from "uplot";

import { readPalette, seriesColor, type ChartPalette } from "@/lib/chart-palette";

import type { SignalBand, SignalPane, SignalSeries } from "./signal-model";

export interface UPlotData {
  readonly data: uPlot.AlignedData;
  readonly series: uPlot.Series[];
  readonly bands: uPlot.Band[];
  readonly xMin: number | null;
  readonly xMax: number | null;
}

function finiteOrNull(value: number | null): number | null {
  return value === null || !Number.isFinite(value) ? null : value;
}

export function buildUPlotData(
  _panes: readonly SignalPane[],
  series: readonly SignalSeries[],
  bands: readonly SignalBand[],
  palette: ChartPalette = readPalette(),
): UPlotData {
  const firstPoints = series[0]?.points ?? bands[0]?.points;
  const x = firstPoints?.map(([time]) => time) ?? [];
  const values: Array<number[] | (number | null)[]> = [x];
  const plotSeries: uPlot.Series[] = [{}];
  const plotBands: uPlot.Band[] = [];

  for (const [index, entry] of series.entries()) {
    values.push(entry.points.map(([, value]) => finiteOrNull(value)));
    plotSeries.push({
      label: entry.name,
      scale: `y${entry.paneIndex}`,
      stroke: seriesColor(palette, entry.measurementClass, index),
      width: 1.4,
      points: { show: false },
    });
  }

  for (const [index, band] of bands.entries()) {
    const minIndex = plotSeries.length;
    values.push(band.points.map(([, min]) => finiteOrNull(min)));
    plotSeries.push({
      label: `${band.name} — reduction minimum`,
      scale: `y${band.paneIndex}`,
      stroke: seriesColor(palette, band.measurementClass, series.length + index),
      width: 0.8,
      points: { show: false },
    });
    const maxIndex = plotSeries.length;
    values.push(band.points.map(([, , max]) => finiteOrNull(max)));
    plotSeries.push({
      label: `${band.name} — reduction maximum`,
      scale: `y${band.paneIndex}`,
      stroke: seriesColor(palette, band.measurementClass, series.length + index),
      width: 0.8,
      points: { show: false },
    });
    plotBands.push({
      series: [minIndex, maxIndex],
      fill: `${seriesColor(palette, band.measurementClass, series.length + index)}33`,
    });
  }

  return {
    data: values as uPlot.AlignedData,
    series: plotSeries,
    bands: plotBands,
    xMin: x.length > 0 ? x[0]! : null,
    xMax: x.length > 0 ? x[x.length - 1]! : null,
  };
}
