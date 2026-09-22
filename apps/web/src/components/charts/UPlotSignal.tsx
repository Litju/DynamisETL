import { useEffect, useMemo, useRef, useState } from "react";
import type uPlot from "uplot";

import { cn } from "@/lib/cn";
import { useAnalysisStore } from "@/lib/state/analysis";
import { rendererTimeMs } from "@/lib/time";

import { buildUPlotData } from "./uplot-data";
import type { SignalBand, SignalPane, SignalSeries } from "./signal-model";

export interface UPlotSignalProps {
  readonly ariaLabel: string;
  readonly className?: string;
  readonly panes: readonly SignalPane[];
  readonly series: readonly SignalSeries[];
  readonly bands: readonly SignalBand[];
  readonly originNs: bigint;
  readonly timeReference?: string;
  readonly playheadMs: number | null;
  readonly rangeMs: { readonly fromMs: number; readonly toMs: number } | null;
  readonly onPointClick?: (selection: { xMs: number }) => void;
  readonly onRangeZoom?: (selection: { fromMs: number; toMs: number }) => void;
}

export function UPlotSignal({
  ariaLabel,
  className,
  panes,
  series,
  bands,
  originNs,
  timeReference,
  playheadMs,
  rangeMs,
  onPointClick,
  onRangeZoom,
}: UPlotSignalProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const playheadRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);
  const callbacksRef = useRef({ onPointClick, onRangeZoom });
  const cleanupResize = useRef<(() => void) | null>(null);
  const initialPlayheadMs = useRef(playheadMs);
  const initialRangeMs = useRef(rangeMs);
  const [ready, setReady] = useState(false);
  const plotData = useMemo(() => buildUPlotData(panes, series, bands), [bands, panes, series]);

  useEffect(() => {
    callbacksRef.current = { onPointClick, onRangeZoom };
  }, [onPointClick, onRangeZoom]);

  useEffect(() => {
    let disposed = false;
    let plot: uPlot | null = null;
    let removeClick: (() => void) | null = null;
    void import("uplot").then(({ default: UPlot }) => {
      const target = containerRef.current;
      if (disposed || target === null || plotData.xMin === null || plotData.xMax === null) return;
      const palette = getComputedStyle(document.documentElement);
      const width = Math.max(320, target.clientWidth || 640);
      const height = Math.max(180, target.clientHeight || 320);
      const xSpan = Math.max(1, plotData.xMax - plotData.xMin);
      const axes: uPlot.Axis[] = [
        {
          scale: "x",
          label: timeReference ? `Time (s relative to ${timeReference})` : "Time (s)",
          stroke: palette.getPropertyValue("--d-chart-axis").trim() || "#8b95a5",
          grid: { stroke: palette.getPropertyValue("--d-chart-grid").trim() || "#28323f", dash: [4, 4] },
          values: (_u, values) => values.map((value) => `${((value - plotData.xMin!) / 1000).toFixed(xSpan > 10000 ? 1 : 3)} s`),
        },
        ...panes.map((pane, index) => ({
          scale: `y${index}`,
          label: pane.unit === "1" ? pane.label : `${pane.label} [${pane.unit}]`,
          stroke: palette.getPropertyValue("--d-chart-axis").trim() || "#8b95a5",
          grid: { stroke: palette.getPropertyValue("--d-chart-grid").trim() || "#28323f" },
          values: (_u: uPlot, values: number[]) => values.map((value) => value.toFixed(2)),
        })),
      ];
      const options: uPlot.Options = {
        width,
        height,
        scales: { x: { time: false }, ...Object.fromEntries(panes.map((_pane, index) => [`y${index}`, { auto: true }])) },
        axes,
        series: plotData.series,
        bands: plotData.bands,
        select: { show: true, left: 0, top: 0, width: 0, height: 0 },
        cursor: { drag: { x: true, y: false }, points: { show: true } },
        legend: { show: plotData.series.length > 2 },
        hooks: {
          setSelect: [
            (instance) => {
              if (instance.select.width < 2) return;
              const fromMs = instance.posToVal(instance.select.left, "x");
              const toMs = instance.posToVal(instance.select.left + instance.select.width, "x");
              callbacksRef.current.onRangeZoom?.({
                fromMs: Math.min(fromMs, toMs),
                toMs: Math.max(fromMs, toMs),
              });
            },
          ],
        },
      };
      plot = new UPlot(options, plotData.data, target);
      plotRef.current = plot;
      const playhead = document.createElement("div");
      playhead.className = "uplot-signal__playhead";
      playhead.setAttribute("aria-hidden", "true");
      plot.over.append(playhead);
      playheadRef.current = playhead;
      const handleClick = (event: MouseEvent) => {
        const rect = plot!.over.getBoundingClientRect();
        const xMs = plot!.posToVal(event.clientX - rect.left, "x");
        if (Number.isFinite(xMs)) callbacksRef.current.onPointClick?.({ xMs });
      };
      plot.over.addEventListener("click", handleClick);
      removeClick = () => plot?.over.removeEventListener("click", handleClick);
      setReady(true);
      updatePlayhead(plot, playhead, initialPlayheadMs.current);
      const initialRange = initialRangeMs.current;
      if (initialRange !== null) {
        plot.setSelect(
          {
            left: plot.valToPos(initialRange.fromMs, "x"),
            top: 0,
            width: Math.max(
              0,
              plot.valToPos(initialRange.toMs, "x") - plot.valToPos(initialRange.fromMs, "x"),
            ),
            height: plot.height,
          },
          false,
        );
      }
      const observer = new ResizeObserver(() => {
        if (!plot) return;
        plot.setSize({ width: Math.max(320, target.clientWidth), height: Math.max(180, target.clientHeight) });
      });
      observer.observe(target);
      cleanupResize.current = () => observer.disconnect();
    });
    return () => {
      disposed = true;
      cleanupResize.current?.();
      cleanupResize.current = null;
      removeClick?.();
      plot?.destroy();
      plotRef.current = null;
      playheadRef.current = null;
      setReady(false);
    };
  }, [panes, plotData, timeReference]);

  const rangeFromMs = rangeMs?.fromMs ?? null;
  const rangeToMs = rangeMs?.toMs ?? null;
  useEffect(() => {
    const plot = plotRef.current;
    if (!plot || rangeFromMs === null || rangeToMs === null) return;
    const left = plot.valToPos(rangeFromMs, "x");
    const right = plot.valToPos(rangeToMs, "x");
    plot.setSelect({ left, top: 0, width: Math.max(0, right - left), height: plot.height }, false);
  }, [rangeFromMs, rangeToMs]);

  useEffect(() => {
    const update = (timeMs: number | null) => {
      const plot = plotRef.current;
      const playhead = playheadRef.current;
      if (!plot || !playhead) return;
      updatePlayhead(plot, playhead, timeMs);
    };
    const current = useAnalysisStore.getState().playheadNs ?? useAnalysisStore.getState().committedTimeNs;
    update(current === null ? null : rendererTimeMs(originNs, current));
    return useAnalysisStore.subscribe((state, previous) => {
      const next = state.playheadNs ?? state.committedTimeNs;
      const before = previous.playheadNs ?? previous.committedTimeNs;
      if (next !== before) update(next === null ? null : rendererTimeMs(originNs, next));
    });
  }, [originNs, playheadMs]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={ariaLabel}
      aria-description="Exact canonical samples or explicitly labeled display-reduced samples with keyboard range selection."
      tabIndex={0}
      data-testid="uplot"
      data-renderer="uplot"
      data-renderer-ready={ready ? "true" : "false"}
      className={cn("uplot-signal h-full min-h-48 w-full", className)}
      onKeyDown={(event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        const plot = plotRef.current;
        if (!plot || plotData.xMin === null || plotData.xMax === null) return;
        event.preventDefault();
        const current = plot.cursor.left === undefined ? plotData.xMin : plot.posToVal(plot.cursor.left, "x");
        const step = Math.max(1, (plotData.xMax - plotData.xMin) / 1000);
        const next = Math.min(plotData.xMax, Math.max(plotData.xMin, current + (event.key === "ArrowRight" ? step : -step)));
        callbacksRef.current.onPointClick?.({ xMs: next });
      }}
    />
  );
}

function updatePlayhead(plot: uPlot, element: HTMLDivElement, timeMs: number | null) {
  if (timeMs === null || !Number.isFinite(timeMs)) {
    element.hidden = true;
    return;
  }
  element.hidden = false;
  element.style.left = `${plot.valToPos(timeMs, "x")}px`;
}
