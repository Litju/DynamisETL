import { useQuery } from "@tanstack/react-query";
import type { ECharts } from "echarts";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { MeasurementClassBadge, ModalityBadge } from "@/components/common/Badges";
import { EChart } from "@/components/charts/EChart";
import {
  buildSignalOption,
  detectBands,
  measureColumns,
  rangeLabel,
  reductionNote,
  toPoints,
  type SignalBand,
  type SignalSeries,
} from "@/components/charts/signal-options";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { StreamView } from "@/api/types";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import { artifactQuery, sessionQuery, windowQuery } from "@/lib/api/queries";
import { readPalette } from "@/lib/chart-palette";
import { useAnalysisStore } from "@/lib/state/analysis";
import { nsFromRendererTime, rendererTimeMs } from "@/lib/time";

const MAX_WINDOW_POINTS = 4000;
const RANGE_COMMIT_DEBOUNCE_MS = 250;

/**
 * Signal laboratory: bounded, display-reduced analytical windows over a
 * canonical or processor-derived stream artifact, with a shared playhead,
 * brush-to-range and exact-unit labels. Science stays on the server.
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
  const artifact = useQuery({
    ...artifactQuery(artifactId ?? ""),
    enabled: Boolean(artifactId),
  });
  const window = useQuery({
    ...windowQuery({
      artifactId: artifactId ?? "",
      ...(fromNs !== null ? { fromNs: Number(fromNs) } : {}),
      ...(toNs !== null ? { toNs: Number(toNs) } : {}),
      maxPoints: MAX_WINDOW_POINTS,
    }),
    enabled: Boolean(artifactId),
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
  if (artifact.isError || window.isError) {
    const error = artifact.error ?? window.error;
    if (error instanceof ApiError && error.state === "dense_window_too_large") {
      return (
        <StatePanel
          state="blocked"
          title="Dense window too large."
          detail="Narrow the time range in the transport or select a shorter trial before requesting this window."
        />
      );
    }
    return (
      <ErrorPanel
        error={error}
        onRetry={() => {
          void artifact.refetch();
          void window.refetch();
        }}
      />
    );
  }
  if (artifact.isPending || window.isPending) {
    return <LoadingPanel label="Loading dense window" />;
  }
  return (
    <SignalView
      artifactMeasurementClass={artifact.data.measurement_class}
      stream={stream}
      unitMap={window.data.meta.units}
      reductionText={reductionNote(window.data.meta)}
      rows={window.data.rows}
      fromNs={fromNs}
      toNs={toNs}
      subjectFilter={subjectFilter}
      sourceRows={window.data.meta.source_rows}
      returnedRows={window.data.meta.returned_rows}
    />
  );
}

function SignalView({
  artifactMeasurementClass,
  stream,
  unitMap,
  reductionText,
  rows,
  fromNs,
  toNs,
  subjectFilter,
  sourceRows,
  returnedRows,
}: {
  artifactMeasurementClass: string | null;
  stream: StreamView;
  unitMap: Record<string, string>;
  reductionText: string | null;
  rows: Array<Record<string, unknown>>;
  fromNs: bigint | null;
  toNs: bigint | null;
  subjectFilter: string | null;
  sourceRows: number;
  returnedRows: number;
}) {
  const context = useAnalysisContext();
  const chartRef = useRef<ECharts | null>(null);
  const commitTimer = useRef<number | null>(null);
  const measurementClass = artifactMeasurementClass ?? stream.measurement_class;
  const first = rows[0];

  const originNs = useMemo(() => {
    const raw = first?.["t_rel_ns"];
    if (typeof raw === "number" || typeof raw === "bigint") return BigInt(raw);
    return fromNs ?? 0n;
  }, [first, fromNs]);

  const columns = useMemo(
    () => measureColumns(Object.keys(first ?? {}), unitMap, first),
    [first, unitMap],
  );
  const bands = useMemo(() => detectBands(Object.keys(first ?? {})), [first]);

  const series = useMemo<SignalSeries[]>(() => {
    if (columns.length === 0) return [];
    const scopedRows =
      subjectFilter === null
        ? rows
        : rows.filter(
            (row) => row["subject_id"] === subjectFilter || row["object_id"] === subjectFilter,
          );
    const subjects = Array.from(
      new Set(
        scopedRows
          .map((row) =>
            typeof row["subject_id"] === "string"
              ? row["subject_id"]
              : typeof row["object_id"] === "string"
                ? row["object_id"]
                : null,
          )
          .filter((value): value is string => value !== null),
      ),
    );
    const groups: Array<{ label: string | null; rows: Array<Record<string, unknown>> }> =
      subjects.length > 1
        ? subjects.map((subject) => ({
            label: subject,
            rows: scopedRows.filter(
              (row) => row["subject_id"] === subject || row["object_id"] === subject,
            ),
          }))
        : [{ label: null, rows: scopedRows }];
    const output: SignalSeries[] = [];
    for (const column of columns) {
      for (const group of groups) {
        if (group.rows.length === 0) continue;
        output.push({
          name: group.label === null ? column : `${group.label} · ${column}`,
          unit: unitMap[column] ?? "1",
          measurementClass,
          points: toPoints(group.rows, column, originNs),
        });
      }
    }
    return output;
  }, [columns, measurementClass, originNs, rows, subjectFilter, unitMap]);

  const bandSeries = useMemo<SignalBand[]>(() => {
    return bands.map((band) => ({
      name: band.base,
      unit: unitMap[band.base] ?? unitMap[band.minKey] ?? "1",
      measurementClass,
      points: rows
        .map((row) => {
          const t = row["t_rel_ns"];
          if (typeof t !== "number" && typeof t !== "bigint") return null;
          const min = row[band.minKey];
          const max = row[band.maxKey];
          return [
            rendererTimeMs(originNs, BigInt(t)),
            typeof min === "number" ? min : null,
            typeof max === "number" ? max : null,
          ] as const;
        })
        .filter(
          (point): point is readonly [number, number | null, number | null] => point !== null,
        ),
    }));
  }, [bands, measurementClass, originNs, rows, unitMap]);

  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const rangeNs = useAnalysisStore((state) => state.committedRangeNs);
  const committedPlayheadMs =
    committedTimeNs === null ? null : rendererTimeMs(originNs, committedTimeNs);

  // The committed playhead is part of the option; live playback is applied
  // imperatively through the chart instance below.
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
                fromMs: rendererTimeMs(originNs, rangeNs.fromNs),
                toMs: rendererTimeMs(originNs, rangeNs.toNs),
              },
        palette: readPalette(),
      }),
    [series, bandSeries, rangeNs, originNs, committedPlayheadMs],
  );

  useEffect(() => {
    const applyPlayhead = (tNs: bigint | null) => {
      const chart = chartRef.current;
      if (!chart) return;
      const ms = tNs === null ? null : rendererTimeMs(originNs, tNs);
      chart.setOption(
        {
          series: [
            {
              id: "series-0",
              markLine: { data: ms === null ? [] : [{ xAxis: ms }] },
            },
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
  }, [originNs]);

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
      const tNs = nsFromRendererTime(originNs, selection.xMs);
      useAnalysisStore.getState().setPlayhead(tNs);
      context?.commitTime(tNs);
    },
    [context, originNs],
  );

  const handleRangeZoom = useCallback(
    (selection: { fromMs: number; toMs: number }) => {
      const range = {
        fromNs: nsFromRendererTime(originNs, selection.fromMs),
        toNs: nsFromRendererTime(originNs, selection.toMs),
      };
      useAnalysisStore.getState().setBrushRange(range);
      if (commitTimer.current !== null) window.clearTimeout(commitTimer.current);
      commitTimer.current = window.setTimeout(() => {
        context?.commitRange(range);
      }, RANGE_COMMIT_DEBOUNCE_MS);
    },
    [context, originNs],
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
        <span className="tabular">
          {sourceRows} source rows → {returnedRows} returned · {rangeLabel(fromNs, toNs)}
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
