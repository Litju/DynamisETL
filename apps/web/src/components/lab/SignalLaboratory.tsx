import { useQuery } from "@tanstack/react-query";
import type { ECharts } from "echarts";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { EChart } from "@/components/charts/EChart";
import {
  buildSignalOption,
  rangeLabel,
  reductionNote,
  type SignalBand,
  type SignalSeries,
} from "@/components/charts/signal-options";
import { useDenseWindow } from "@/components/lab/use-dense-window";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { sessionQuery } from "@/lib/api/queries";
import {
  bandPairs,
  bandPointsFor,
  entityKeys,
  measureColumns,
  originNs,
  pointsFor,
  type WindowTable,
} from "@/lib/arrow/window-table";
import { readPalette } from "@/lib/chart-palette";
import { useAnalysisStore } from "@/lib/state/analysis";
import { nsFromRendererTime, rendererTimeMs } from "@/lib/time";

const MAX_WINDOW_POINTS = 4000;
const RANGE_COMMIT_DEBOUNCE_MS = 250;

/**
 * Signal laboratory: bounded, display-reduced analytical windows over a
 * canonical or processor-derived stream artifact. Dense transport prefers Arrow
 * IPC decoded in a worker; JSON remains the metadata fallback. Playback updates
 * go straight to the chart instance, never through React state.
 */
export function SignalLaboratory() {
  const context = useAnalysisContext();
  const datasetId = context?.datasetId ?? null;
  const sessionId = context?.sessionId ?? null;
  const streamId = context?.streamId ?? null;
  const fromNs = context?.fromNs ?? null;
  const toNs = context?.toNs ?? null;
  const subjectFilter = context?.subjectId ?? null;

  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const stream: StreamView | null = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((candidate) => candidate.stream_id === streamId) ?? null;
  }, [session.data, streamId]);
  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const dense = useDenseWindow({
    artifactId,
    ...(fromNs !== null ? { fromNs: Number(fromNs) } : {}),
    ...(toNs !== null ? { toNs: Number(toNs) } : {}),
    maxPoints: MAX_WINDOW_POINTS,
  });

  if (!context) {
    return <StatePanel state="empty" title="Open a laboratory session first." />;
  }
  if (session.isPending) {
    return <LoadingPanel label="Loading session streams" />;
  }
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }
  if (streamId === null) {
    return (
      <StatePanel
        state="empty"
        title="No stream selected."
        detail="Select a stream in the explorer to load its bounded signal window."
      />
    );
  }
  if (stream === null) {
    return (
      <StatePanel
        state="unavailable"
        title="Stream is not part of this session."
        detail="The selected stream does not belong to the open session; cross-session synchronization is never inferred."
      />
    );
  }
  if (artifactId === null) {
    return (
      <StatePanel
        state="unavailable"
        title="No canonical artifact is registered for this stream."
        detail="Run the deterministic ingest path to materialize canonical Parquet before analysis."
      />
    );
  }
  if (dense.isError) {
    const error = dense.error;
    if (error instanceof ApiError && error.state === "dense_window_too_large") {
      return (
        <StatePanel
          state="blocked"
          title="Dense window too large."
          detail="Narrow the time range in the transport or select a shorter trial before requesting this window."
        />
      );
    }
    return <ErrorPanel error={error} onRetry={() => void dense.refetch()} />;
  }
  if (dense.isPending || dense.data.table === null) {
    return <LoadingPanel label="Loading dense window" />;
  }
  return (
    <SignalView
      stream={stream}
      table={dense.data.table}
      transport={dense.data.transport ?? "json"}
      fromNs={fromNs}
      toNs={toNs}
      subjectFilter={subjectFilter}
    />
  );
}

function SignalView({
  stream,
  table,
  transport,
  fromNs,
  toNs,
  subjectFilter,
}: {
  stream: StreamView;
  table: WindowTable;
  transport: "arrow" | "json";
  fromNs: bigint | null;
  toNs: bigint | null;
  subjectFilter: string | null;
}) {
  const context = useAnalysisContext();
  const chartRef = useRef<ECharts | null>(null);
  const commitTimer = useRef<number | null>(null);
  const measurementClass = table.meta.artifact.measurement_class ?? stream.measurement_class;
  const origin = useMemo(() => originNs(table), [table]);
  const measures = useMemo(() => measureColumns(table), [table]);
  const bands = useMemo(() => bandPairs(table), [table]);
  const groups = useMemo(() => entityKeys(table), [table]);
  const unitMap = table.meta.units;
  const reductionText = reductionNote(table.meta);

  const scopedGroups = useMemo(() => {
    if (groups.length === 0) return [{ id: null as string | null, rows: allRows(table) }];
    const filtered =
      subjectFilter === null ? groups : groups.filter((group) => group.id === subjectFilter);
    return filtered.length > 0 ? filtered : [];
  }, [groups, subjectFilter, table]);

  const series = useMemo<SignalSeries[]>(() => {
    if (measures.length === 0) return [];
    const output: SignalSeries[] = [];
    for (const column of measures) {
      for (const group of scopedGroups) {
        if (group.rows.length === 0) continue;
        output.push({
          name: group.id === null ? column : `${group.id} · ${column}`,
          unit: unitMap[column] ?? "1",
          measurementClass,
          points: pointsFor(table, column, group.rows, origin),
        });
      }
    }
    return output;
  }, [measurementClass, measures, origin, scopedGroups, table, unitMap]);

  const bandSeries = useMemo<SignalBand[]>(() => {
    return bands.map((band) => ({
      name: band.base,
      unit: unitMap[band.base] ?? unitMap[band.minKey] ?? "1",
      measurementClass,
      points: bandPointsFor(table, band.minKey, band.maxKey, origin),
    }));
  }, [bands, measurementClass, origin, table, unitMap]);

  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const rangeNs = useAnalysisStore((state) => state.committedRangeNs);
  const committedPlayheadMs =
    committedTimeNs === null ? null : rendererTimeMs(origin, committedTimeNs);

  const option = useMemo(
    () =>
      buildSignalOption({
        series,
        bands: bandSeries,
        playheadMs: committedPlayheadMs,
        rangeMs:
          rangeNs === null
            ? null
            : {
                fromMs: rendererTimeMs(origin, rangeNs.fromNs),
                toMs: rendererTimeMs(origin, rangeNs.toNs),
              },
        palette: readPalette(),
      }),
    [series, bandSeries, rangeNs, origin, committedPlayheadMs],
  );

  useEffect(() => {
    const applyPlayhead = (tNs: bigint | null) => {
      const chart = chartRef.current;
      if (!chart) return;
      const ms = tNs === null ? null : rendererTimeMs(origin, tNs);
      chart.setOption(
        {
          series: [
            { id: "series-0", markLine: { data: ms === null ? [] : [{ xAxis: ms }] } },
          ],
        },
        { lazyUpdate: true },
      );
    };
    return useAnalysisStore.subscribe((state, previous) => {
      const next = state.playheadNs ?? state.committedTimeNs;
      const before = previous.playheadNs ?? previous.committedTimeNs;
      if (next === before) return;
      applyPlayhead(next);
    });
  }, [origin]);

  useEffect(() => {
    return () => {
      if (commitTimer.current !== null) window.clearTimeout(commitTimer.current);
    };
  }, []);

  const handleReady = useCallback((chart: ECharts) => {
    chartRef.current = chart;
  }, []);

  const handlePointClick = useCallback(
    (selection: { xMs: number }) => {
      if (!Number.isFinite(selection.xMs)) return;
      const tNs = nsFromRendererTime(origin, selection.xMs);
      useAnalysisStore.getState().setPlayhead(tNs);
      context?.commitTime(tNs);
    },
    [context, origin],
  );

  const handleRangeZoom = useCallback(
    (selection: { fromMs: number; toMs: number }) => {
      const range = {
        fromNs: nsFromRendererTime(origin, selection.fromMs),
        toNs: nsFromRendererTime(origin, selection.toMs),
      };
      useAnalysisStore.getState().setBrushRange(range);
      if (commitTimer.current !== null) window.clearTimeout(commitTimer.current);
      commitTimer.current = window.setTimeout(() => {
        context?.commitRange(range);
      }, RANGE_COMMIT_DEBOUNCE_MS);
    },
    [context, origin],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex min-h-9 shrink-0 flex-wrap items-center gap-3 border-b border-border-subtle bg-surface-1 px-3 py-1 text-[11px] text-text-muted">
        <ModalityBadge modality={stream.modality} />
        <span className="mono">{stream.stream_id}</span>
        <MeasurementClassBadge measurementClass={measurementClass} compact />
        <span className="mono">sync {stream.synchronization_spec_id}</span>
        <span className="mono">frame {stream.coordinate_frame_id ?? "unavailable"}</span>
        <span className="mono">{stream.nominal_sampling_rate_hz ?? "?"} Hz</span>
        <span className="mono" title="Dense transport actually used for this window">
          transport {transport}
        </span>
        <span className="tabular">
          {table.meta.source_rows} source rows → {table.meta.returned_rows} returned ·{" "}
          {rangeLabel(fromNs, toNs)}
        </span>
        {reductionText ? (
          <span className="text-quality-warning">{reductionText}</span>
        ) : (
          <span>exact samples in this window</span>
        )}
      </header>
      {series.length === 0 && bandSeries.length === 0 ? (
        <StatePanel
          state="empty"
          title="No numeric measure columns are present in this window."
          detail="Select another stream or widen the time range; non-numeric identity columns are never plotted."
        />
      ) : (
        <div className="min-h-0 flex-1">
          <EChart
            ariaLabel={`Signal window for ${stream.stream_id}`}
            option={option}
            onReady={handleReady}
            onPointClick={handlePointClick}
            onRangeZoom={handleRangeZoom}
          />
        </div>
      )}
    </div>
  );
}

function allRows(table: WindowTable): number[] {
  return Array.from({ length: table.rowCount }, (_value, index) => index);
}
