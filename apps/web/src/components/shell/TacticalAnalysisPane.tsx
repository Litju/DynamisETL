import type { EChartsOption } from "echarts";
import { PanelRightClose } from "lucide-react";
import { useMemo } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import type { ArtifactRef, TacticalCapabilityView } from "@/api/types";
import { EChart } from "@/components/charts/EChart";
import { MeasurementClassBadge } from "@/components/common/Badges";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { KeyValueRow, Panel, SectionTitle } from "@/components/common/Panel";
import { useAnalysisContext } from "@/lib/analysis-context";
import {
  tacticalArtifactsQuery,
  tacticalCapabilitiesQuery,
  tacticalSeriesQuery,
} from "@/lib/api/queries";
import type { TacticalView } from "@/lib/search";
import { useAnalysisStore } from "@/lib/state/analysis";

const TABS: ReadonlyArray<[TacticalView, string]> = [
  ["live", "Live"],
  ["space", "Space"],
  ["shape", "Shape"],
  ["range", "Range"],
  ["events", "Events"],
  ["report", "Report"],
];

function numberValue(row: Record<string, unknown>, key: string): number | null {
  const value = row[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metricText(value: number | null, unit: string): string {
  return value === null ? "—" : `${value.toFixed(2)} ${unit}`;
}

function artifactFor(artifacts: readonly ArtifactRef[], seriesName: string): ArtifactRef | null {
  return artifacts.find((artifact) => artifact.artifact_metadata?.series_name === seriesName) ?? null;
}

function nearestRow(rows: readonly Record<string, unknown>[], timeNs: bigint | null) {
  if (rows.length === 0) return null;
  if (timeNs === null) return rows[0] ?? null;
  return rows.reduce((best, row) => {
    const time = numberValue(row, "t_rel_ns");
    const bestTime = numberValue(best, "t_rel_ns");
    if (time === null) return best;
    if (bestTime === null) return row;
    return Math.abs(time - Number(timeNs)) < Math.abs(bestTime - Number(timeNs)) ? row : best;
  }, rows[0]!);
}

function rangeStats(rows: readonly Record<string, unknown>[], key: string) {
  const values = rows
    .map((row) => numberValue(row, key))
    .filter((value): value is number => value !== null);
  if (values.length === 0) return null;
  return {
    mean: values.reduce((sum, value) => sum + value, 0) / values.length,
    min: Math.min(...values),
    max: Math.max(...values),
  };
}

function Unavailable({ reason }: { reason: string }) {
  return <StatePanel state="unavailable" title="Unavailable for this source" detail={reason} />;
}

function Evidence({
  measurementClass,
  method,
}: {
  measurementClass: string;
  method: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface-0 px-3 py-2 text-[11px]">
      <MeasurementClassBadge measurementClass={measurementClass} compact />
      <span className="text-text-muted">{method}</span>
    </div>
  );
}

export function TacticalAnalysisPane({ onCollapse }: { onCollapse?: () => void } = {}) {
  const context = useAnalysisContext();
  const currentTimeNs = useAnalysisStore((state) => state.playheadNs ?? state.committedTimeNs);
  const capabilities = useQuery({
    ...tacticalCapabilitiesQuery(context?.datasetId ?? ""),
    enabled: Boolean(context?.datasetId),
  });
  const artifacts = useQuery({
    ...tacticalArtifactsQuery({
      datasetId: context?.datasetId ?? "",
      sessionId: context?.sessionId,
      streamId: context?.streamId ?? undefined,
    }),
    enabled: Boolean(context?.datasetId),
  });
  const view = context?.tacticalView ?? "live";
  const teamArtifact = artifactFor(artifacts.data ?? [], "team_geometry");
  const territoryArtifact = artifactFor(artifacts.data ?? [], "team_territory");
  const eventArtifact = artifactFor(artifacts.data ?? [], "source_event_snapshots");
  const influenceArtifact = artifactFor(artifacts.data ?? [], "team_influence");
  const range = context?.fromNs !== null && context?.toNs !== null
    ? { fromNs: context?.fromNs ?? 0n, toNs: context?.toNs ?? 0n }
    : null;
  const liveBounds = currentTimeNs === null
    ? null
    : { fromNs: currentTimeNs - 1_000_000_000n, toNs: currentTimeNs + 1_000_000_000n };
  const bounds = range ?? liveBounds;
  const teamSeries = useQuery({
    ...tacticalSeriesQuery({
      artifactId: teamArtifact?.artifact_id ?? "",
      fromNs: bounds ? Number(bounds.fromNs) : undefined,
      toNs: bounds ? Number(bounds.toNs) : undefined,
      maxPoints: view === "range" || view === "report" ? 5_000 : 400,
    }),
    enabled: Boolean(teamArtifact && bounds),
  });
  const territorySeries = useQuery({
    ...tacticalSeriesQuery({
      artifactId: territoryArtifact?.artifact_id ?? "",
      fromNs: bounds ? Number(bounds.fromNs) : undefined,
      toNs: bounds ? Number(bounds.toNs) : undefined,
      maxPoints: 1_000,
    }),
    enabled: Boolean(territoryArtifact && view === "space" && bounds),
  });
  const influenceSeries = useQuery({
    ...tacticalSeriesQuery({
      artifactId: influenceArtifact?.artifact_id ?? "",
      fromNs: bounds ? Number(bounds.fromNs) : undefined,
      toNs: bounds ? Number(bounds.toNs) : undefined,
      maxPoints: 1_000,
    }),
    enabled: Boolean(influenceArtifact && view === "space" && bounds),
  });
  const eventSeries = useQuery({
    ...tacticalSeriesQuery({
      artifactId: eventArtifact?.artifact_id ?? "",
      fromNs: bounds ? Number(bounds.fromNs) : undefined,
      toNs: bounds ? Number(bounds.toNs) : undefined,
      maxPoints: 2_000,
    }),
    enabled: Boolean(eventArtifact && view === "events" && bounds),
  });

  if (!context) return <StatePanel state="empty" title="Open a laboratory session first." />;
  if (capabilities.isPending || artifacts.isPending) return <LoadingPanel label="Loading tactical capability" />;
  if (capabilities.isError) return <ErrorPanel error={capabilities.error} onRetry={() => void capabilities.refetch()} />;
  if (artifacts.isError) return <ErrorPanel error={artifacts.error} onRetry={() => void artifacts.refetch()} />;
  const capability = capabilities.data;
  const rows = (teamSeries.data?.rows ?? []) as Record<string, unknown>[];
  const current = nearestRow(rows, currentTimeNs);
  const measurementClass = teamSeries.data?.meta.measurement_class ?? "PIPELINE_DERIVED";

  return (
    <Panel
      title="Tactical Analysis"
      className="border-l border-border-subtle"
      bodyClassName="flex flex-col overflow-hidden"
      actions={
        onCollapse ? (
          <button
            type="button"
            onClick={onCollapse}
            aria-label="Collapse tactical analysis"
            title="Collapse tactical analysis"
            className="flex size-5 items-center justify-center rounded-[3px] text-text-muted hover:bg-surface-2 hover:text-text-secondary"
          >
            <PanelRightClose size={13} aria-hidden="true" />
          </button>
        ) : null
      }
    >
      <div className="shrink-0 border-b border-border-subtle bg-surface-1 px-2 py-1.5">
        <div role="tablist" aria-label="Tactical analysis views" className="flex flex-wrap gap-1">
          {TABS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={view === value}
              onClick={() => context.selectTacticalView?.(value)}
              className={view === value
                ? "rounded-control border border-accent bg-surface-3 px-2 py-1 text-[11px] text-text-primary"
                : "rounded-control border border-border-subtle px-2 py-1 text-[11px] text-text-muted hover:text-text-secondary"}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <Evidence measurementClass={measurementClass} method="Canonical processor output; source capabilities govern availability." />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {view === "live" ? <LiveTab row={current} capability={capability} /> : null}
        {view === "space" ? (
          <SpaceTab
            capability={capability}
            territoryRows={(territorySeries.data?.rows ?? []) as Record<string, unknown>[]}
            influenceRows={(influenceSeries.data?.rows ?? []) as Record<string, unknown>[]}
          />
        ) : null}
        {view === "shape" ? (
          <Unavailable reason={capability.capabilities.level_e_shape_phase === "unavailable"
            ? "The accepted tracking slices do not pass the temporal shape/phase gate. No formation or phase label is inferred."
            : "Shape output is available only through a versioned stable-window model."} />
        ) : null}
        {view === "range" ? <RangeTab rows={rows} /> : null}
        {view === "events" ? (
          <EventsTab
            rows={(eventSeries.data?.rows ?? []) as Record<string, unknown>[]}
            onSeek={(timeNs) => context.commitTime(timeNs)}
            unavailable={capability.capabilities.level_d_event_linked === "unavailable"}
          />
        ) : null}
        {view === "report" ? (
          <ReportTab
            datasetId={context.datasetId}
            sessionId={context.sessionId}
            rows={rows}
            events={(eventSeries.data?.rows ?? []) as Record<string, unknown>[]}
            capability={capability}
          />
        ) : null}
      </div>
      <div className="flex shrink-0 flex-wrap gap-3 border-t border-border-subtle bg-surface-1 px-3 py-2 text-[11px]">
        <Link to="/methods" className="text-accent hover:underline">Method authority</Link>
        <Link to="/runs" className="text-accent hover:underline">Runs / provenance</Link>
        <Link to="/quality" className="text-accent hover:underline">Quality / rights</Link>
      </div>
    </Panel>
  );
}

function LiveTab({ row, capability }: { row: Record<string, unknown> | null; capability: TacticalCapabilityView }) {
  if (capability.capabilities.level_a_geometry === "unavailable_for_pitch_team_geometry") {
    return <Unavailable reason="This source has no full-team pitch geometry authority." />;
  }
  if (!row) return <StatePanel state="empty" title="No tactical frame at the current time." detail="Select an exact tracking time or load a tactical processor artifact." />;
  return (
    <div className="p-3">
      <SectionTitle>Current frame · frame-axis geometry</SectionTitle>
      <div className="grid grid-cols-2 gap-2">
        <KeyValueRow label="Group"><span className="mono">{String(row.group_id ?? "—")}</span></KeyValueRow>
        <KeyValueRow label="Players" mono>{String(row.player_count ?? "—")}</KeyValueRow>
        <KeyValueRow label="Centroid X" mono>{metricText(numberValue(row, "centroid_x_m"), "m")}</KeyValueRow>
        <KeyValueRow label="Centroid Y" mono>{metricText(numberValue(row, "centroid_y_m"), "m")}</KeyValueRow>
        <KeyValueRow label="Length" mono>{metricText(numberValue(row, "length_m"), "m")}</KeyValueRow>
        <KeyValueRow label="Width" mono>{metricText(numberValue(row, "width_m"), "m")}</KeyValueRow>
        <KeyValueRow label="Hull area" mono>{metricText(numberValue(row, "hull_area_m2"), "m²")}</KeyValueRow>
        <KeyValueRow label="Stretch" mono>{metricText(numberValue(row, "stretch_index"), "1")}</KeyValueRow>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
        Frame-axis values are deterministic geometry. Attacking direction, possession and pressure are not inferred from this view.
      </p>
    </div>
  );
}

function SpaceTab({
  capability,
  territoryRows,
  influenceRows,
}: {
  capability: TacticalCapabilityView;
  territoryRows: Record<string, unknown>[];
  influenceRows: Record<string, unknown>[];
}) {
  if (capability.capabilities.level_b_territory === "unavailable") return <Unavailable reason="This source has no opposing-team pitch tracking, so geometric territory is unavailable." />;
  const territory = territoryRows[0];
  const influence = influenceRows[0];
  return (
    <div className="p-3">
      <SectionTitle>Space · bounded geometry and influence</SectionTitle>
      {territory ? (
        <KeyValueRow label="Control" mono>{metricText(numberValue(territory, "control_percentage"), "%")}</KeyValueRow>
      ) : <p className="text-[12px] text-text-muted">No clipped territory rows are served for this range.</p>}
      {influence ? (
        <KeyValueRow label="Influence" mono>{metricText(numberValue(influence, "influence_percentage"), "%")}</KeyValueRow>
      ) : null}
      <p className="mt-3 text-[11px] leading-relaxed text-text-muted">
        Voronoi control is geometric territory, not possession probability. Influence is a model-estimated arrival surface with versioned assumptions.
      </p>
    </div>
  );
}

function RangeTab({ rows }: { rows: Record<string, unknown>[] }) {
  const length = rangeStats(rows, "length_m");
  const width = rangeStats(rows, "width_m");
  const option = useMemo<EChartsOption>(() => ({
    animation: false,
    grid: { left: 38, right: 12, top: 20, bottom: 24 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", name: "canonical ms" },
    yAxis: { type: "value", name: "m" },
    series: [
      { name: "length", type: "line", showSymbol: false, data: rows.flatMap((row) => {
        const x = numberValue(row, "t_rel_ns");
        const y = numberValue(row, "length_m");
        return x === null || y === null ? [] : [[x / 1e6, y]];
      }) },
      { name: "width", type: "line", showSymbol: false, data: rows.flatMap((row) => {
        const x = numberValue(row, "t_rel_ns");
        const y = numberValue(row, "width_m");
        return x === null || y === null ? [] : [[x / 1e6, y]];
      }) },
    ],
  }), [rows]);
  if (rows.length === 0) return <StatePanel state="empty" title="No tactical range rows." />;
  return (
    <div className="p-3">
      <SectionTitle>Range statistics</SectionTitle>
      <div className="grid grid-cols-2 gap-2">
        <KeyValueRow label="Length mean" mono>{metricText(length?.mean ?? null, "m")}</KeyValueRow>
        <KeyValueRow label="Length min/max" mono>{length ? `${length.min.toFixed(2)} / ${length.max.toFixed(2)} m` : "—"}</KeyValueRow>
        <KeyValueRow label="Width mean" mono>{metricText(width?.mean ?? null, "m")}</KeyValueRow>
        <KeyValueRow label="Width min/max" mono>{width ? `${width.min.toFixed(2)} / ${width.max.toFixed(2)} m` : "—"}</KeyValueRow>
      </div>
      <div className="mt-3 h-48"><EChart option={option} ariaLabel="Tactical length and width over selected range" /></div>
      <p className="mt-2 text-[11px] leading-relaxed text-text-muted">Statistics describe the selected range; they do not make causal or performance judgements.</p>
    </div>
  );
}

function EventsTab({ rows, onSeek, unavailable }: { rows: Record<string, unknown>[]; onSeek: (timeNs: bigint) => void; unavailable: boolean }) {
  if (unavailable) return <Unavailable reason="This accepted source has no synchronized event artifact." />;
  if (rows.length === 0) return <StatePanel state="empty" title="No source events in the selected range." />;
  return (
    <div className="divide-y divide-border-subtle/60">
      {rows.map((row, index) => {
        const time = numberValue(row, "t_rel_ns");
        return (
          <button key={String(row.event_id ?? index)} type="button" onClick={() => time === null ? undefined : onSeek(BigInt(Math.trunc(time)))} className="block w-full px-3 py-2 text-left hover:bg-surface-2">
            <div className="flex items-baseline justify-between gap-2 text-[12px] text-text-secondary"><span>{String(row.event_type ?? "source event")} {row.event_subtype ? `· ${String(row.event_subtype)}` : ""}</span><span className="mono text-[10px] text-text-muted">{time === null ? "—" : `${(time / 1e9).toFixed(3)} s`}</span></div>
            <div className="mt-1 text-[10px] text-text-muted">Source event preserved · tracking snapshot {row.tracking_t_rel_ns == null ? "not synchronized" : "synchronized"}</div>
          </button>
        );
      })}
    </div>
  );
}

function ReportTab({ datasetId, sessionId, rows, events, capability }: { datasetId: string; sessionId: string; rows: Record<string, unknown>[]; events: Record<string, unknown>[]; capability: TacticalCapabilityView }) {
  const report = useMemo(() => JSON.stringify({
    dataset_id: datasetId,
    session_id: sessionId,
    team_geometry_rows: rows.length,
    source_event_rows: events.length,
    capability: capability.capabilities,
    unavailable_reasons: capability.unavailable_reasons,
    conclusion_policy: "quantitative summary only; unsupported tactical conclusions are omitted",
  }, null, 2), [capability, datasetId, events.length, rows.length, sessionId]);
  const download = () => {
    const url = URL.createObjectURL(new Blob([report], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `tactical-report-${datasetId}-${sessionId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="p-3">
      <SectionTitle>Deterministic report</SectionTitle>
      <p className="text-[11px] leading-relaxed text-text-muted">Quantitative rows, event counts, capability disclosure and provenance pointers only. No unsupported natural-language tactical conclusion is generated.</p>
      <button type="button" onClick={download} className="mt-3 rounded-control border border-border-strong px-2 py-1 text-[11px] text-text-secondary hover:bg-surface-3">Download JSON report</button>
      <pre className="mono mt-3 max-h-64 overflow-auto rounded-control border border-border-subtle bg-surface-0 p-2 text-[10px] text-text-muted">{report}</pre>
      <Link to="/quality" className="mt-3 inline-block text-[11px] text-accent hover:underline">Open quality and rights evidence →</Link>
    </div>
  );
}
