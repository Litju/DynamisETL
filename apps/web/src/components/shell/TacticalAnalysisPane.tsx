import type { EChartsOption } from "echarts";
import { PanelRightClose } from "lucide-react";
import { useMemo, useRef, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import type { ArtifactRef, TacticalCapabilityView } from "@/api/types";
import { EChart } from "@/components/charts/EChart";
import { MeasurementClassBadge } from "@/components/common/Badges";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { SectionTitle } from "@/components/common/Panel";
import { sessionTeams } from "@/components/pitch/PitchReplay";
import {
  ALGORITHMS,
  LEVEL_NAMES,
  bucketBounds,
  byTeam,
  liveReadWindow,
  levelArtifact,
  levelStatus,
  numberOf,
  reportPayload,
  rowsAtFrame,
  type LevelStatus,
  type TacticalLevel,
} from "@/components/shell/tactical-pane-model";
import type { TacticalRow } from "@/components/pitch/tactical-overlay";
import { useThrottledPlayhead } from "@/hooks/useThrottledPlayhead";
import { useAnalysisContext } from "@/lib/analysis-context";
import { ApiError } from "@/lib/api/client";
import {
  sessionQuery,
  tacticalArtifactsQuery,
  tacticalCapabilitiesQuery,
  tacticalSeriesQuery,
} from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import type { TacticalView } from "@/lib/search";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatClockNs, formatDurationNs } from "@/lib/time";

const TABS: ReadonlyArray<readonly [TacticalView, string]> = [
  ["live", "Live"],
  ["space", "Space"],
  ["shape", "Shape"],
  ["range", "Range"],
  ["events", "Events"],
  ["report", "Report"],
];

/** Live/Space read windows: one query per 30 s of canonical time. */
const LIVE_BUCKET_NS = 30_000_000_000n;
/** Covers the drawn frame and a sampled grid just before a bucket boundary. */
const LIVE_LOOKBACK_NS = 2_000_000_000n;
/** Events follow a wider bucket when no range is committed. */
const EVENT_BUCKET_NS = 120_000_000_000n;
const EXACT_MAX_POINTS = 100_000;
/** Range tab refuses ranges whose exact rows would not fit one request. */
const MAX_RANGE_NS = 20n * 60n * 1_000_000_000n;
/** "Use playhead ±15 s" range helper. */
const RANGE_HALF_NS = 15_000_000_000n;

const TEAM_COLOURS = ["var(--d-team-a)", "var(--d-team-b)"] as const;

function formatValue(value: number | null, unit: string, digits = 1): string {
  if (value === null) return "—";
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

interface TeamContext {
  readonly order: readonly string[];
  readonly labels: ReadonlyMap<string, string>;
}

function TeamName({ groupId, teams }: { groupId: string; teams: TeamContext }) {
  const index = teams.order.indexOf(groupId);
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5" title={groupId}>
      <span
        aria-hidden="true"
        className="inline-block size-2 shrink-0 self-start rounded-full mt-1"
        style={{ backgroundColor: TEAM_COLOURS[index] ?? "var(--d-text-muted)" }}
      />
      <span className="min-w-0 break-words text-left leading-tight">{teams.labels.get(groupId) ?? groupId}</span>
    </span>
  );
}

/** State for a level that cannot show values, with the authority that decided. */
function LevelState({ level, status }: { level: TacticalLevel; status: LevelStatus }) {
  if (status.kind === "unsupported") {
    return (
      <StatePanel
        state="unsupported"
        title={`${LEVEL_NAMES[level]} is not supported for this source.`}
        detail={
          <div className="space-y-1.5 text-left">
            <p>
              Capability authority: <span className="mono">{status.capability}</span>
            </p>
            {status.reasons.length > 0 ? (
              <ul className="list-disc space-y-0.5 pl-4">
                {status.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : null}
            <p>No value is inferred or zero-filled.</p>
          </div>
        }
      />
    );
  }
  if (status.kind === "not_materialized") {
    return (
      <StatePanel
        state="not_materialized"
        title={`${LEVEL_NAMES[level]} is supported but no processor output is registered locally.`}
        detail={
          <div className="space-y-1.5">
            <p>
              Algorithm <span className="mono">{status.algorithmId}</span> has not been run for this
              stream.
            </p>
            <p>
              Prepare the local corpus with <span className="mono">uv run dynamis-demo-prepare</span>{" "}
              (see <span className="mono">docs/DEMO-RUNBOOK.md</span>).
            </p>
          </div>
        }
      />
    );
  }
  return null;
}

/** A two-team comparison table; rows are metrics, columns are teams. */
function TeamTable({
  teams,
  rows,
  metrics,
  caption,
}: {
  teams: TeamContext;
  rows: ReadonlyArray<{ groupId: string; row: TacticalRow }>;
  metrics: ReadonlyArray<{ key: string; label: string; unit: string; digits?: number }>;
  caption: string;
}) {
  return (
    <table className="w-full table-fixed border-collapse text-[12px]">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-border-subtle">
          <th scope="col" className="w-[38%] py-1.5 text-left text-[11px] font-normal text-text-muted">
            metric
          </th>
          {rows.map(({ groupId }) => (
            <th key={groupId} scope="col" className="py-1.5 pl-2 text-right text-[11px] font-medium text-text-secondary">
              <span className="inline-flex max-w-full justify-end">
                <TeamName groupId={groupId} teams={teams} />
              </span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric) => (
          <tr key={metric.key} className="border-b border-border-subtle/50 last:border-b-0">
            <th scope="row" className="py-1.5 text-left text-[11px] font-normal text-text-muted">
              {metric.label}
              {metric.unit ? <span className="ml-1 text-text-muted">{metric.unit}</span> : null}
            </th>
            {rows.map(({ groupId, row }) => (
              <td key={groupId} className="mono py-1.5 pl-2 text-right tabular text-text-primary">
                {formatValue(numberOf(row, metric.key), "", metric.digits ?? 1)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ClassLine({ measurementClass, method }: { measurementClass: string; method: ReactNode }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
      <MeasurementClassBadge measurementClass={measurementClass} compact />
      <span>{method}</span>
    </div>
  );
}

export function TacticalAnalysisPane({ onCollapse }: { onCollapse?: () => void } = {}) {
  const context = useAnalysisContext();
  const timeNs = useThrottledPlayhead(200);
  const selectedEntityId = useAnalysisStore((state) => state.selectedEntityId);
  const datasetId = context?.datasetId ?? "";
  const session = useQuery({
    ...sessionQuery(datasetId, context?.sessionId ?? ""),
    enabled: Boolean(context?.datasetId && context?.sessionId),
  });
  const capabilities = useQuery({
    ...tacticalCapabilitiesQuery(datasetId),
    enabled: Boolean(context?.datasetId),
  });
  const artifacts = useQuery({
    ...tacticalArtifactsQuery({
      datasetId,
      sessionId: context?.sessionId,
      streamId: context?.streamId ?? undefined,
    }),
    enabled: Boolean(context?.datasetId && context?.streamId),
  });
  const view: TacticalView = context?.tacticalView ?? "live";
  const stream = session.data?.streams.find((item) => item.stream_id === context?.streamId) ?? null;
  const frameAgeNs = 1.5 * (1e9 / (stream?.nominal_sampling_rate_hz && stream.nominal_sampling_rate_hz > 0 ? stream.nominal_sampling_rate_hz : 25));
  const teams = useMemo(() => sessionTeams(session.data), [session.data]);
  const statuses = useMemo(() => {
    if (!capabilities.data) return null;
    const list = artifacts.data ?? [];
    return {
      A: levelStatus("A", capabilities.data, list),
      B: levelStatus("B", capabilities.data, list),
      C: levelStatus("C", capabilities.data, list),
      D: levelStatus("D", capabilities.data, list),
      E: levelStatus("E", capabilities.data, list),
    } as const;
  }, [artifacts.data, capabilities.data]);

  const range = context?.fromNs !== null && context?.fromNs !== undefined && context?.toNs !== null && context?.toNs !== undefined
    ? { fromNs: context.fromNs, toNs: context.toNs }
    : null;
  const liveWindow = timeNs === null ? null : liveReadWindow(timeNs, LIVE_BUCKET_NS, LIVE_LOOKBACK_NS);
  const eventWindow = range ?? (timeNs === null ? null : bucketBounds(timeNs, EVENT_BUCKET_NS));
  const seriesQuery = (artifact: ArtifactRef | null, bounds: { fromNs: bigint; toNs: bigint } | null, enabled: boolean) => ({
    ...tacticalSeriesQuery({
      artifactId: artifact?.artifact_id ?? "",
      fromNs: bounds ? Number(bounds.fromNs) : undefined,
      toNs: bounds ? Number(bounds.toNs) : undefined,
      maxPoints: EXACT_MAX_POINTS,
    }),
    enabled: Boolean(artifact && bounds) && enabled,
  });
  const teamGeometry = statuses ? levelArtifact(statuses.A, "team_geometry") : null;
  const teamTerritory = statuses ? levelArtifact(statuses.B, "team_territory") : null;
  const teamInfluence = statuses ? levelArtifact(statuses.C, "team_influence") : null;
  const eventSnapshots = statuses ? levelArtifact(statuses.D, "source_event_snapshots") : null;
  const rangeTooLong = range !== null && range.toNs - range.fromNs > MAX_RANGE_NS;
  const liveGeometry = useQuery(seriesQuery(teamGeometry, liveWindow, view === "live"));
  const liveTerritory = useQuery(seriesQuery(teamTerritory, liveWindow, view === "space"));
  const liveInfluence = useQuery(seriesQuery(teamInfluence, liveWindow, view === "space"));
  const rangeGeometry = useQuery(seriesQuery(teamGeometry, range, (view === "range" || view === "report") && !rangeTooLong));
  const events = useQuery(seriesQuery(eventSnapshots, eventWindow, view === "events" || view === "report"));

  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const target = event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : (index + delta + TABS.length) % TABS.length;
    if (delta === 0 && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const next = TABS[target]![0];
    context?.selectTacticalView?.(next);
    tabRefs.current[target]?.focus();
  };

  if (!context) return <StatePanel state="empty" title="Open a laboratory session first." />;

  const participant = selectedEntityId === null
    ? null
    : (session.data?.participants.find((item) => item.subject_id === selectedEntityId) ?? null);
  const selectedLabel = selectedEntityId === null
    ? null
    : participant
      ? `${participant.notes ?? participant.subject_id}${participant.cohort ? ` · ${participant.cohort}` : ""}`
      : `${selectedEntityId} (tracked object, not a registered participant)`;

  let body: ReactNode;
  if (!context.streamId) {
    body = <StatePanel state="empty" title="Select a tracking stream." detail="Tactical analysis follows the Field stream." />;
  } else if (capabilities.isPending || artifacts.isPending) {
    body = <LoadingPanel label="Loading tactical capability" />;
  } else if (capabilities.isError) {
    body = capabilities.error instanceof ApiError && capabilities.error.status === 404
      ? <StatePanel state="unsupported" title="No tactical capability authority exists for this dataset." detail="Tactical analysis is limited to sources in the tactical capability matrix." />
      : <ErrorPanel error={capabilities.error} onRetry={() => void capabilities.refetch()} />;
  } else if (artifacts.isError) {
    body = <ErrorPanel error={artifacts.error} onRetry={() => void artifacts.refetch()} />;
  } else if (statuses && capabilities.data) {
    const capability = capabilities.data;
    if (view === "live") {
      body = statuses.A.kind !== "available"
        ? <LevelState level="A" status={statuses.A} />
        : <LiveTab query={liveGeometry} rows={rowsAtFrame(liveGeometry.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs)} teams={teams} />;
    } else if (view === "space") {
      body = (
        <SpaceTab
          statusB={statuses.B}
          statusC={statuses.C}
          territory={liveTerritory}
          influence={liveInfluence}
          territoryRows={rowsAtFrame(liveTerritory.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs)}
          influenceRows={rowsAtFrame(liveInfluence.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs)}
          teams={teams}
        />
      );
    } else if (view === "shape") {
      body = <LevelState level="E" status={statuses.E.kind === "available" ? { kind: "unsupported", capability: statuses.E.capability, reasons: capability.unavailable_reasons } : statuses.E} />;
    } else if (view === "range") {
      body = statuses.A.kind !== "available"
        ? <LevelState level="A" status={statuses.A} />
        : <RangeTab range={range} tooLong={rangeTooLong} query={rangeGeometry} teams={teams} timeNs={timeNs} onCommitRange={context.commitRange} />;
    } else if (view === "events") {
      body = statuses.D.kind !== "available"
        ? <LevelState level="D" status={statuses.D} />
        : <EventsTab query={events} window={eventWindow} explicitRange={range !== null} timeNs={timeNs} teams={teams} onSeek={(target) => {
            useAnalysisStore.getState().setPlayhead(target);
            context.commitTime(target);
          }} />;
    } else {
      body = (
        <ReportTab
          payload={reportPayload({
            datasetId: context.datasetId,
            sessionId: context.sessionId,
            streamId: context.streamId,
            timeNs,
            range,
            capability,
            statuses,
            teamLabels: teams.labels,
            rangeTeamRows: rangeGeometry.data?.rows.length ?? 0,
            eventRows: events.data?.rows.length ?? 0,
          })}
          datasetId={context.datasetId}
          sessionId={context.sessionId}
        />
      );
    }
  } else {
    body = <LoadingPanel label="Loading tactical capability" />;
  }

  return (
    <section aria-label="Tactical Analysis" className="flex h-full min-h-0 flex-col border-l border-border-subtle bg-surface-1">
      <header className="shrink-0 border-b border-border-subtle">
        <div className="flex h-8 items-center justify-between gap-2 px-3">
          <h2 className="t-section truncate text-text-muted">Tactical Analysis</h2>
          {onCollapse ? (
            <button
              type="button"
              onClick={onCollapse}
              aria-label="Collapse tactical analysis"
              title="Collapse tactical analysis"
              className="flex size-6 items-center justify-center rounded-control text-text-muted hover:bg-surface-2 hover:text-text-secondary"
            >
              <PanelRightClose size={13} aria-hidden="true" />
            </button>
          ) : null}
        </div>
        <dl data-testid="tactical-context" className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 px-3 pb-2 text-[11px]">
          <dt className="text-text-muted">Period</dt>
          <dd className="mono truncate text-text-secondary">{context.trialId ?? "—"} · {context.streamId ?? "no stream"}</dd>
          <dt className="text-text-muted">Frame</dt>
          <dd className="mono tabular text-text-primary">{timeNs === null ? "—" : formatClockNs(timeNs)}</dd>
          <dt className="text-text-muted">Selected</dt>
          <dd className="truncate text-text-secondary">{selectedLabel ?? "none (click a player or the ball)"}</dd>
        </dl>
        <div role="tablist" aria-label="Tactical analysis views" className="flex h-8 items-end gap-0.5 overflow-x-auto px-2">
          {TABS.map(([value, label], index) => (
            <button
              key={value}
              ref={(element) => { tabRefs.current[index] = element; }}
              id={`tactical-tab-${value}`}
              type="button"
              role="tab"
              aria-selected={view === value}
              aria-controls="tactical-tabpanel"
              tabIndex={view === value ? 0 : -1}
              onClick={() => context.selectTacticalView?.(value)}
              onKeyDown={(event) => onTabKey(event, index)}
              className={cn(
                "relative h-7 shrink-0 rounded-t-control px-2 text-[11px] transition-colors duration-quick",
                view === value ? "font-medium text-text-primary" : "text-text-muted hover:text-text-secondary",
              )}
            >
              {label}
              {view === value ? (
                <span aria-hidden="true" className="t-tab-indicator absolute inset-x-1.5 bottom-0 h-0.5 rounded-full bg-accent" />
              ) : null}
            </button>
          ))}
        </div>
      </header>
      <div
        id="tactical-tabpanel"
        role="tabpanel"
        aria-labelledby={`tactical-tab-${view}`}
        data-testid="tactical-tabpanel"
        data-view={view}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {body}
      </div>
      <nav aria-label="Tactical evidence" className="flex shrink-0 flex-wrap gap-3 border-t border-border-subtle bg-surface-1 px-3 py-2 text-[11px]">
        <Link to="/methods" className="text-accent hover:underline">Method authority</Link>
        <Link to="/runs" search={{ dataset: context.datasetId }} className="text-accent hover:underline">Runs / provenance</Link>
        <Link to="/quality" search={{ dataset: context.datasetId }} className="text-accent hover:underline">Quality / rights</Link>
      </nav>
    </section>
  );
}

type SeriesQuery = ReturnType<typeof useQuery<{ rows: unknown[]; meta: { measurement_class: string; returned_rows: number; source_rows: number } }>>;

function queryState(query: SeriesQuery): ReactNode | null {
  if (query.isPending && query.fetchStatus !== "idle") return <LoadingPanel label="Loading tactical series" />;
  if (query.isError) return <ErrorPanel error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data && query.data.meta.returned_rows !== query.data.meta.source_rows) {
    return <StatePanel state="blocked" title="The served window was display-reduced." detail="Exact tactical rows are required; values from a reduced window are not shown." />;
  }
  return null;
}

function LiveTab({ query, rows, teams }: { query: SeriesQuery; rows: readonly TacticalRow[]; teams: TeamContext }) {
  const state = queryState(query);
  if (state) return state;
  const teamRows = byTeam(rows, teams.order);
  if (teamRows.length === 0) {
    return <StatePanel state="no_frame" title="No team geometry row at this frame." detail="The tracking frame at the playhead has no Level A output (for example a frame without both teams)." />;
  }
  return (
    <div className="p-3">
      <SectionTitle>Current frame · team geometry</SectionTitle>
      <TeamTable
        teams={teams}
        rows={teamRows}
        caption="Level A team geometry at the current frame"
        metrics={[
          { key: "player_count", label: "Players", unit: "", digits: 0 },
          { key: "centroid_x_m", label: "Centroid x", unit: "m" },
          { key: "centroid_y_m", label: "Centroid y", unit: "m" },
          { key: "length_m", label: "Length", unit: "m" },
          { key: "width_m", label: "Width", unit: "m" },
          { key: "hull_area_m2", label: "Hull area", unit: "m²", digits: 0 },
          { key: "stretch_index", label: "Stretch index", unit: "ratio", digits: 3 },
        ]}
      />
      <ClassLine
        measurementClass={query.data?.meta.measurement_class ?? "PIPELINE_DERIVED"}
        method={<>Deterministic geometry of <span className="mono">{ALGORITHMS.A}</span> on the pitch frame axes.</>}
      />
      <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
        Length and width are along the pitch x/y axes; attacking direction, possession and pressure are not inferred.
      </p>
    </div>
  );
}

function SpaceTab({
  statusB,
  statusC,
  territory,
  influence,
  territoryRows,
  influenceRows,
  teams,
}: {
  statusB: LevelStatus;
  statusC: LevelStatus;
  territory: SeriesQuery;
  influence: SeriesQuery;
  territoryRows: readonly TacticalRow[];
  influenceRows: readonly TacticalRow[];
  teams: TeamContext;
}) {
  return (
    <div className="space-y-4 p-3">
      <section aria-label="Territory">
        <SectionTitle>Territory · clipped Voronoi (Level B)</SectionTitle>
        {statusB.kind !== "available" ? (
          <LevelState level="B" status={statusB} />
        ) : (
          queryState(territory) ?? (
            byTeam(territoryRows, teams.order).length === 0 ? (
              <StatePanel state="no_frame" title="No territory row at this frame." className="min-h-16 p-2" />
            ) : (
              <>
                <TeamTable teams={teams} rows={byTeam(territoryRows, teams.order)} caption="Level B territory share at the current frame" metrics={[{ key: "control_percentage", label: "Pitch share", unit: "%" }]} />
                <ClassLine measurementClass={territory.data?.meta.measurement_class ?? "PIPELINE_DERIVED"} method="Geometric territory, not possession probability." />
              </>
            )
          )
        )}
      </section>
      <section aria-label="Influence">
        <SectionTitle>Influence · arrival-time model (Level C)</SectionTitle>
        {statusC.kind !== "available" ? (
          <LevelState level="C" status={statusC} />
        ) : (
          queryState(influence) ?? (
            byTeam(influenceRows, teams.order).length === 0 ? (
              <StatePanel state="no_frame" title="No influence summary at this frame." className="min-h-16 p-2" />
            ) : (
              <>
                <TeamTable teams={teams} rows={byTeam(influenceRows, teams.order)} caption="Level C influence share at the current frame" metrics={[{ key: "influence_percentage", label: "Grid share", unit: "%" }]} />
                <ClassLine measurementClass={influence.data?.meta.measurement_class ?? "MODEL_ESTIMATED"} method="Versioned kinematic arrival-time assumptions; not measured territory." />
              </>
            )
          )
        )}
      </section>
    </div>
  );
}

function RangeTab({
  range,
  tooLong,
  query,
  teams,
  timeNs,
  onCommitRange,
}: {
  range: { fromNs: bigint; toNs: bigint } | null;
  tooLong: boolean;
  query: SeriesQuery;
  teams: TeamContext;
  timeNs: bigint | null;
  onCommitRange: (range: { fromNs: bigint; toNs: bigint } | null) => void;
}) {
  const rows = useMemo(() => (query.data?.rows ?? []) as TacticalRow[], [query.data]);
  const series = useMemo(() => {
    const grouped = new Map<string, TacticalRow[]>();
    for (const row of rows) {
      const groupId = row["group_id"];
      if (typeof groupId !== "string") continue;
      const bucket = grouped.get(groupId) ?? [];
      bucket.push(row);
      grouped.set(groupId, bucket);
    }
    return byTeam([...grouped.values()].map((list) => list[0]!), teams.order).map(({ groupId }) => ({
      groupId,
      rows: grouped.get(groupId) ?? [],
    }));
  }, [rows, teams.order]);
  const option = useMemo<EChartsOption>(() => ({
    animation: false,
    grid: { left: 40, right: 10, top: 28, bottom: 28 },
    legend: { top: 0, textStyle: { fontSize: 10 } },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", name: "s", nameGap: 4, axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", name: "m", axisLabel: { fontSize: 10 } },
    series: series.flatMap(({ groupId, rows: teamRows }, index) => {
      const colour = index === 0 ? "#8fc7ef" : "#f0b454";
      const label = teams.labels.get(groupId) ?? groupId;
      const points = (key: string) => teamRows.flatMap((row) => {
        const x = numberOf(row, "t_rel_ns");
        const y = numberOf(row, key);
        return x === null || y === null ? [] : [[x / 1e9, y]];
      });
      return [
        { name: `${label} length`, type: "line" as const, showSymbol: false, lineStyle: { width: 1.25, color: colour }, itemStyle: { color: colour }, data: points("length_m") },
        { name: `${label} width`, type: "line" as const, showSymbol: false, lineStyle: { width: 1.25, type: "dashed" as const, color: colour }, itemStyle: { color: colour }, data: points("width_m") },
      ];
    }),
  }), [series, teams.labels]);
  if (range === null) {
    return (
      <StatePanel
        state="empty"
        title="No range is committed."
        detail="Range statistics describe an explicit committed interval, never an implicit window."
        action={
          timeNs !== null ? (
            <button
              type="button"
              onClick={() => onCommitRange({ fromNs: timeNs - RANGE_HALF_NS, toNs: timeNs + RANGE_HALF_NS })}
              className="t-control rounded-control border border-border-strong px-2 text-[11px] text-text-secondary hover:bg-surface-3"
            >
              Commit playhead ± 15 s
            </button>
          ) : null
        }
      />
    );
  }
  if (tooLong) {
    return <StatePanel state="blocked" title="The committed range is longer than 20 minutes." detail="Narrow the range; range statistics use exact rows only." />;
  }
  const state = queryState(query);
  if (state) return state;
  if (series.length === 0) return <StatePanel state="filtered" title="No team geometry rows in the committed range." />;
  const stat = (teamRows: TacticalRow[], key: string) => {
    const values = teamRows.map((row) => numberOf(row, key)).filter((value): value is number => value !== null);
    if (values.length === 0) return null;
    return { mean: values.reduce((sum, value) => sum + value, 0) / values.length, min: Math.min(...values), max: Math.max(...values), n: values.length };
  };
  return (
    <div className="p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <SectionTitle>Committed range · {formatDurationNs(range.toNs - range.fromNs)}</SectionTitle>
        <button type="button" onClick={() => onCommitRange(null)} className="text-[11px] text-accent hover:underline">Clear range</button>
      </div>
      <table className="w-full table-fixed border-collapse text-[11px]">
        <caption className="sr-only">Length and width statistics per team over the committed range</caption>
        <thead>
          <tr className="border-b border-border-subtle text-text-muted">
            <th scope="col" className="py-1 text-left font-normal">team</th>
            <th scope="col" className="py-1 text-right font-normal">length mean · min–max (m)</th>
            <th scope="col" className="py-1 text-right font-normal">width mean · min–max (m)</th>
          </tr>
        </thead>
        <tbody>
          {series.map(({ groupId, rows: teamRows }) => {
            const length = stat(teamRows, "length_m");
            const width = stat(teamRows, "width_m");
            const cell = (value: ReturnType<typeof stat>) => value === null ? "—" : `${value.mean.toFixed(1)} · ${value.min.toFixed(1)}–${value.max.toFixed(1)}`;
            return (
              <tr key={groupId} className="border-b border-border-subtle/50">
                <th scope="row" className="py-1.5 text-left font-normal text-text-secondary"><TeamName groupId={groupId} teams={teams} /></th>
                <td className="mono py-1.5 text-right tabular text-text-primary">{cell(length)}</td>
                <td className="mono py-1.5 text-right tabular text-text-primary">{cell(width)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-3 h-52"><EChart option={option} ariaLabel="Team length (solid) and width (dashed) over the committed range" /></div>
      <ClassLine measurementClass={query.data?.meta.measurement_class ?? "PIPELINE_DERIVED"} method={`${rows.length} exact rows · descriptive statistics only, no causal or performance judgement.`} />
    </div>
  );
}

function EventsTab({
  query,
  window,
  explicitRange,
  timeNs,
  teams,
  onSeek,
}: {
  query: SeriesQuery;
  window: { fromNs: bigint; toNs: bigint } | null;
  explicitRange: boolean;
  timeNs: bigint | null;
  teams: TeamContext;
  onSeek: (timeNs: bigint) => void;
}) {
  const state = queryState(query);
  if (state) return state;
  const rows = ((query.data?.rows ?? []) as TacticalRow[]).slice().sort((left, right) => (numberOf(left, "t_rel_ns") ?? 0) - (numberOf(right, "t_rel_ns") ?? 0));
  const scope = window === null ? "" : `${explicitRange ? "committed range" : "2-minute window"} ${formatClockNs(window.fromNs)}–${formatClockNs(window.toNs)}`;
  if (rows.length === 0) {
    return <StatePanel state="filtered" title="No source events in this window." detail={scope} />;
  }
  const current = timeNs === null ? null : Number(timeNs);
  return (
    <div>
      <p className="border-b border-border-subtle px-3 py-1.5 text-[11px] text-text-muted">
        {rows.length} source events · {scope}. Provider labels preserved; nothing is relabelled.
      </p>
      <ul aria-label="Source events" className="divide-y divide-border-subtle/60">
        {rows.map((row, index) => {
          const time = numberOf(row, "t_rel_ns");
          const synced = row["tracking_t_rel_ns"] !== null && row["tracking_t_rel_ns"] !== undefined;
          const team = typeof row["provider_team_id"] === "string" ? row["provider_team_id"] : null;
          const near = current !== null && time !== null && Math.abs(time - current) < 1e9;
          return (
            <li key={String(row["event_id"] ?? index)}>
              <button
                type="button"
                onClick={() => (time === null ? undefined : onSeek(BigInt(Math.trunc(time))))}
                aria-current={near ? "true" : undefined}
                className={cn("block w-full px-3 py-2 text-left hover:bg-surface-2", near && "bg-surface-3")}
                title="Seek the playhead to this event"
              >
                <div className="flex items-baseline justify-between gap-2 text-[12px] text-text-secondary">
                  <span className="truncate">
                    {String(row["event_type"] ?? "source event")}
                    {row["event_subtype"] ? <span className="text-text-muted"> · {String(row["event_subtype"])}</span> : null}
                  </span>
                  <span className="mono shrink-0 text-[10px] text-text-muted">{time === null ? "—" : formatClockNs(BigInt(Math.trunc(time)))}</span>
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-text-muted">
                  {team ? <TeamName groupId={team} teams={teams} /> : <span>no team</span>}
                  <span>· tracking snapshot {synced ? "synchronized" : "not synchronized"}</span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ReportTab({ payload, datasetId, sessionId }: { payload: Record<string, unknown>; datasetId: string; sessionId: string }) {
  const text = useMemo(() => JSON.stringify(payload, null, 2), [payload]);
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `tactical-report-${datasetId}-${sessionId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="p-3">
      <SectionTitle>Deterministic report</SectionTitle>
      <p className="text-[11px] leading-relaxed text-text-muted">
        Identities, capability status per level, artifact/run provenance and counts. No natural-language tactical conclusion is generated.
      </p>
      <button type="button" onClick={download} className="t-control mt-3 rounded-control border border-border-strong px-2 text-[11px] text-text-secondary hover:bg-surface-3">
        Download JSON report
      </button>
      <pre data-testid="tactical-report" tabIndex={0} aria-label="Tactical report JSON" className="mono mt-3 max-h-[28rem] overflow-auto rounded-control border border-border-subtle bg-surface-0 p-2 text-[10px] text-text-muted">{text}</pre>
    </div>
  );
}

export type { TacticalCapabilityView };
