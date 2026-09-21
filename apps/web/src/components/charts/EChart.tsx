import type { ECElementEvent, ECharts, EChartsOption } from "echarts";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/cn";

export interface ChartPointSelection {
  readonly xMs: number;
  readonly dataIndex: number;
  readonly seriesName: string | null;
}

export interface ChartRangeSelection {
  readonly fromMs: number;
  readonly toMs: number;
}

export interface EChartProps {
  readonly option: EChartsOption;
  readonly ariaLabel: string;
  readonly className?: string;
  readonly onReady?: (chart: ECharts) => void;
  readonly onPointClick?: (selection: ChartPointSelection) => void;
  readonly onRangeZoom?: (selection: ChartRangeSelection) => void;
}

/**
 * Small internal ECharts lifecycle component.
 *
 * ECharts is the only general analytical chart engine in V1. The chart instance
 * lives outside React: options are applied imperatively, resize is observed, and
 * playback-frequency updates go through `instance.setOption` instead of React
 * state. The engine module is imported lazily so catalog routes never download it.
 */
export function EChart({
  option,
  ariaLabel,
  className,
  onReady,
  onPointClick,
  onRangeZoom,
}: EChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ECharts | null>(null);
  const callbacksRef = useRef({ onPointClick, onRangeZoom, onReady });
  useEffect(() => {
    callbacksRef.current = { onPointClick, onRangeZoom, onReady };
  }, [onPointClick, onRangeZoom, onReady]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let disposed = false;
    let chart: ECharts | null = null;
    let observer: ResizeObserver | null = null;
    void import("echarts").then((echarts) => {
      const element = containerRef.current;
      if (disposed || element === null) return;
      chart = echarts.init(element, undefined, { renderer: "canvas" });
      chartRef.current = chart;
      chart.on("click", (params: ECElementEvent) => {
        const data = params.data as [number, number] | undefined;
        callbacksRef.current.onPointClick?.({
          xMs: Array.isArray(data) ? Number(data[0]) : Number.NaN,
          dataIndex: params.dataIndex ?? -1,
          seriesName: params.seriesName ?? null,
        });
      });
      // ECharts types model zrender events; dataZoom is an action event.
      // The handle must stay bound: ECharts guards `on` against a disposed
      // instance through `this`, so a detached reference throws before any
      // series is ever drawn.
      const onAction = chart.on.bind(chart) as (event: string, handler: () => void) => void;
      onAction("dataZoom", () => {
        const option = chart?.getOption();
        const zoom = option?.dataZoom as
          | Array<{ start?: number; end?: number }>
          | { start?: number; end?: number }
          | undefined;
        const first = Array.isArray(zoom) ? zoom[0] : zoom;
        const start = Number(first?.start ?? 0);
        const end = Number(first?.end ?? 100);
        const xAxis = (option?.xAxis as Array<{ min?: number; max?: number }> | undefined)?.[0];
        const min = Number(xAxis?.min ?? 0);
        const max = Number(xAxis?.max ?? 0);
        const span = max - min;
        callbacksRef.current.onRangeZoom?.({
          fromMs: min + (span * start) / 100,
          toMs: min + (span * end) / 100,
        });
      });
      observer = new ResizeObserver(() => {
        chart?.resize();
      });
      observer.observe(element);
      setReady(true);
      callbacksRef.current.onReady?.(chart);
    });
    return () => {
      disposed = true;
      observer?.disconnect();
      chart?.dispose();
      chartRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    if (!ready) return;
    chartRef.current?.setOption(option, { notMerge: true, lazyUpdate: true });
  }, [option, ready]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={ariaLabel}
      data-testid="echart"
      data-renderer="echarts"
      data-renderer-ready={ready ? "true" : "false"}
      className={cn("h-full min-h-48 w-full", className)}
    />
  );
}
