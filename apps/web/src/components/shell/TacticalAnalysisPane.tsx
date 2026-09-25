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
import { ARRIVAL_TIME_ELEVATION_SPEC, describeElevationSpec } from "@/components/matchlab/elevation-specs";
import { maximumFrameAgeNs, sessionTeams } from "@/components/pitch/pitch-model";
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
import { jsonIds } from "@/components/pitch/tactical-v3";
import { useThrottledPlayhead } from "@/hooks/useThrottledPlayhead";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useMatchFrameContext } from "@/lib/match-frame-context";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
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
import type { ScalarFieldMode, TacticalRelationMode } from "@/lib/state/analysis";
import { formatClockNs, formatDurationNs } from "@/lib/time";

const TABS: ReadonlyArray<readonly [TacticalView, string]> = [
  ["live", "Live"],
  ["structure", "Structure"],
  ["relations", "Relations"],
  ["space", "Space"],
  ["events", "Events"],
  ["range", "Range"],
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

export function TacticalAnalysisPane({
  onCollapse,
  embedded = false,
  reportOnly = false,
}: {
  readonly onCollapse?: () => void;
  readonly embedded?: boolean;
  readonly reportOnly?: boolean;
} = {}) {
  const context = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
  const timeNs = useThrottledPlayhead(200);
  const selectedEntityId =
    matchFrame?.selectedTrackingObjectId ?? context?.subjectId ?? context?.entityId ?? null;
  const datasetId = context?.datasetId ?? "";
  const relationMode = useAnalysisStore((state) => state.tacticalRelationMode);
  const scalarFieldMode = useAnalysisStore((state) => state.scalarFieldMode);
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
  const frameAgeNs = maximumFrameAgeNs(stream?.nominal_sampling_rate_hz);
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
      V3: levelStatus("V3", capabilities.data, list),
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
  const functionalUnits = statuses ? levelArtifact(statuses.V3, "functional_unit_geometry") : null;
  const shapeEdges = statuses ? levelArtifact(statuses.V3, "shape_graph_edges") : null;
  const triangles = statuses ? levelArtifact(statuses.V3, "tactical_triangles") : null;
  const interactions = statuses ? levelArtifact(statuses.V3, "attacker_defender_interactions") : null;
  const sourceContext = statuses ? levelArtifact(statuses.V3, "source_possession_context") : null;
  const occupiedArea = statuses ? levelArtifact(statuses.A, "team_geometry") : null;
  const eventSnapshots = statuses ? levelArtifact(statuses.D, "source_event_snapshots") : null;
  const rangeTooLong = range !== null && range.toNs - range.fromNs > MAX_RANGE_NS;
  const liveUnits = useQuery(seriesQuery(functionalUnits, liveWindow, view === "live" || view === "structure"));
  const liveSourceContext = useQuery(seriesQuery(sourceContext, liveWindow, view === "live"));
  const liveEdges = useQuery(seriesQuery(shapeEdges, liveWindow, view === "relations" && relationMode === "stable-graph" && (selectedEntityId !== null || Boolean(matchFrame?.selectedTeamId))));
  const liveTriangles = useQuery(seriesQuery(triangles, liveWindow, view === "relations" && relationMode === "selected-triangles" && selectedEntityId !== null));
  const liveInteractions = useQuery(seriesQuery(interactions, liveWindow, view === "relations" && relationMode === "attacker-defender" && selectedEntityId !== null));
  const liveOccupiedArea = useQuery(seriesQuery(occupiedArea, liveWindow, view === "space"));
  const liveTerritory = useQuery(seriesQuery(teamTerritory, liveWindow, view === "space"));
  const liveInfluence = useQuery(seriesQuery(teamInfluence, liveWindow, view === "space"));
  const rangeGeometry = useQuery(seriesQuery(teamGeometry, range, (view === "range" || view === "report") && !rangeTooLong));
  const events = useQuery(seriesQuery(eventSnapshots, eventWindow, view === "events" || view === "report"));
  const exactUnits = rowsAtFrame(liveUnits.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs);
  const exactSourceContext = rowsAtFrame(liveSourceContext.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs);
  const exactEdges = rowsAtFrame(liveEdges.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs);
  const exactTriangles = rowsAtFrame(liveTriangles.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs);
  const exactInteractions = rowsAtFrame(liveInteractions.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs);

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
      body = statuses.V3.kind !== "available"
        ? <LevelState level="V3" status={statuses.V3} />
        : (
          <LiveTab
            unitsQuery={liveUnits}
            contextQuery={liveSourceContext}
            unitRows={exactUnits}
            contextRows={exactSourceContext}
            teams={teams}
            selectedEntityId={selectedEntityId}
            matchFrame={matchFrame}
          />
        );
    } else if (view === "structure") {
      body = statuses.V3.kind !== "available"
        ? <LevelState level="V3" status={statuses.V3} />
        : (
          <StructureTab
            query={liveUnits}
            rows={exactUnits}
            teams={teams}
            selectedEntityId={selectedEntityId}
            matchFrame={matchFrame}
            detail
          />
        );
    } else if (view === "relations") {
      body = statuses.V3.kind !== "available"
        ? <LevelState level="V3" status={statuses.V3} />
        : (
          <RelationsTab
            mode={relationMode}
            setMode={(mode) => useAnalysisStore.getState().setTacticalRelationMode(mode)}
            selectedEntityId={selectedEntityId}
            teamId={matchFrame?.selectedTeamId ?? null}
            teams={teams}
            edgesQuery={liveEdges}
            trianglesQuery={liveTriangles}
            interactionsQuery={liveInteractions}
            edges={exactEdges}
            triangles={exactTriangles}
            interactions={exactInteractions}
            matchFrame={matchFrame}
          />
        );
    } else if (view === "space") {
      body = (
        <SpaceTab
          statusA={statuses.A}
          statusB={statuses.B}
          statusC={statuses.C}
          occupiedArea={liveOccupiedArea}
          occupiedRows={rowsAtFrame(liveOccupiedArea.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs)}
          territory={liveTerritory}
          influence={liveInfluence}
          territoryRows={rowsAtFrame(liveTerritory.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs)}
          influenceRows={rowsAtFrame(liveInfluence.data?.rows as TacticalRow[] | undefined, timeNs, frameAgeNs)}
          teams={teams}
          scalarMode={scalarFieldMode}
          setScalarMode={(mode) => useAnalysisStore.getState().setScalarFieldMode(mode)}
        />
      );
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
          compact={reportOnly}
        />
      );
    }
  } else {
    body = <LoadingPanel label="Loading tactical capability" />;
  }

  if (reportOnly) {
    return <div data-testid="tactical-report-section">{body}</div>;
  }

  return (
    <section aria-label="Tactical Analysis" className={`flex h-full min-h-0 flex-col bg-surface-1 ${embedded ? "" : "border-l border-border-subtle"}`}>
      <header className="shrink-0 border-b border-border-subtle">
        {!embedded ? <>
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
        </> : null}
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
      {!embedded ? <nav aria-label="Tactical evidence" className="flex shrink-0 flex-wrap gap-3 border-t border-border-subtle bg-surface-1 px-3 py-2 text-[11px]">
        <Link to="/methods" className="text-accent hover:underline">Method authority</Link>
        <Link to="/runs" search={{ dataset: context.datasetId }} className="text-accent hover:underline">Runs / provenance</Link>
        <Link to="/quality" search={{ dataset: context.datasetId }} className="text-accent hover:underline">Quality / rights</Link>
      </nav> : null}
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

function SourceContext({ rows, teams }: { rows: readonly TacticalRow[]; teams: TeamContext }) {
  const row = rows[0];
  if (!row) {
    return <p className="mt-2 text-[11px] text-text-muted">No source possession context is recorded at this exact frame.</p>;
  }
  const teamId = row["source_possession_team_id"];
  const ballStatus = row["source_ball_status"];
  const ballX = numberOf(row, "ball_x_m");
  const ballY = numberOf(row, "ball_y_m");
  return (
    <div className="mt-2 grid grid-cols-2 gap-2 rounded-control border border-border-subtle bg-surface-2/60 p-2 text-[11px]">
      <div>
        <div className="text-text-muted">Source possession</div>
        <div className="mt-0.5 text-text-primary">
          {typeof teamId === "string" ? <TeamName groupId={teamId} teams={teams} /> : "unknown"}
          {typeof ballStatus === "string" ? <span className="ml-1.5 text-text-muted">· {ballStatus} ball</span> : null}
        </div>
      </div>
      <div>
        <div className="text-text-muted">Ball · {typeof row["ball_zone_frame"] === "string" ? String(row["ball_zone_frame"]).replaceAll("_", " ") : "frame axis"}</div>
        <div className="mono mt-0.5 tabular text-text-primary">
          {ballX === null || ballY === null ? "no finite point" : `${ballX.toFixed(1)}, ${ballY.toFixed(1)} m`}
          {typeof row["ball_zone"] === "string" ? ` · ${row["ball_zone"]}` : ""}
        </div>
      </div>
      <div className="col-span-2"><ClassLine measurementClass="SOURCE_DERIVED" method="Provider context and the ball point from this frame; no possession-by-proximity inference." /></div>
    </div>
  );
}

function StructureTab({
  query,
  rows,
  teams,
  selectedEntityId,
  matchFrame,
  detail = false,
}: {
  query: SeriesQuery;
  rows: readonly TacticalRow[];
  teams: TeamContext;
  selectedEntityId: string | null;
  matchFrame: MatchFrameContextValue | null;
  detail?: boolean;
}) {
  const state = queryState(query);
  if (state) return state;
  const teamRows = byTeam(rows, teams.order);
  const groupIds = [...new Set(teamRows.map((item) => item.groupId))];
  if (teamRows.length === 0) return <StatePanel state="no_frame" title="No functional-unit geometry at this exact frame." detail="V3 uses source roster roles; missing players and roles remain missing or unknown." />;
  return (
    <div className="space-y-3 p-3">
      <SectionTitle>DEF / MID / ATT · current frame</SectionTitle>
      {groupIds.map((groupId) => {
        const units = teamRows.filter((item) => item.groupId === groupId).map((item) => item.row);
        const ordered = ["GK", "DEF", "MID", "ATT", "unknown"].flatMap((role) => units.filter((row) => row["functional_unit"] === role));
        const first = ordered[0];
        return (
          <section key={groupId} className="rounded-control border border-border-subtle bg-surface-1 p-2.5">
            <div className="mb-2 flex items-center justify-between gap-2 text-[11px]">
              <TeamName groupId={groupId} teams={teams} />
              <span className="text-text-muted">{first?.["coordinate_normalization"] === "team_attack_positive_x" ? "attack-axis coordinates" : "source-frame coordinates"}</span>
            </div>
            <div className="space-y-1.5">
              {ordered.map((row) => {
                const role = String(row["functional_unit"] ?? "unknown");
                const memberIds = jsonIds(row["role_ids_json"]);
                const isSelected = selectedEntityId !== null && memberIds.includes(selectedEntityId);
                return (
                  <div key={`${groupId}:${role}`} className={cn("rounded border px-2 py-1.5", isSelected ? "border-accent/70 bg-accent/5" : "border-border-subtle/70")}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-semibold tracking-wide text-text-primary">{role}</span>
                      <span className="mono text-[10px] tabular text-text-muted">n={numberOf(row, "player_count") ?? 0}</span>
                    </div>
                    <div className="mt-0.5 grid grid-cols-3 gap-1 text-[10px] text-text-muted">
                      <span>line {formatValue(numberOf(row, "line_height_x_m"), "m")}</span>
                      <span>depth {formatValue(numberOf(row, "depth_x_m"), "m")}</span>
                      <span>width {formatValue(numberOf(row, "width_y_m"), "m")}</span>
                    </div>
                    {detail ? (
                      <div className="mt-0.5 grid grid-cols-2 gap-1 text-[10px] text-text-muted">
                        <span>centroid {formatValue(numberOf(row, "centroid_x_m"), "m")}, {formatValue(numberOf(row, "centroid_y_m"), "m")}</span>
                        <span>dispersion {formatValue(numberOf(row, "dispersion_rms_m"), "m")}</span>
                        <span>principal axis {formatValue(numberOf(row, "orientation_deg"), "°")}</span>
                        <span>major/minor 1σ {formatValue(numberOf(row, "major_axis_sd_m"), "m")} / {formatValue(numberOf(row, "minor_axis_sd_m"), "m")}</span>
                      </div>
                    ) : null}
                    {memberIds.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {memberIds.map((id) => (
                          <button key={id} type="button" data-player-id={id} aria-pressed={id === selectedEntityId} onClick={() => matchFrame?.selectTrackingObject(id, "player")} className={cn("mono rounded px-1 py-0.5 text-[9px]", id === selectedEntityId ? "bg-accent text-surface-0" : "bg-surface-3 text-text-secondary hover:text-text-primary")} title="Select this source-tracked player in Field and Pose">
                            {id.length > 13 ? id.slice(-8) : id}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-text-muted">
              <span>DEF↔MID gap {formatValue(numberOf(first, "def_mid_gap_m"), "m")}</span>
              <span>MID↔ATT gap {formatValue(numberOf(first, "mid_att_gap_m"), "m")}</span>
              <span>outfield block depth {formatValue(numberOf(first, "outfield_block_depth_m"), "m")}</span>
            </div>
          </section>
        );
      })}
      <ClassLine measurementClass={query.data?.meta.measurement_class ?? "PIPELINE_DERIVED"} method={<>Source-roster roles · <span className="mono">{ALGORITHMS.V3}</span> v2 · exact-frame geometry.</>} />
      <p className="text-[10px] leading-relaxed text-text-muted">Inter-line gaps are absolute coordinate separations; they do not label formation, pressing, or phase.</p>
    </div>
  );
}

function LiveTab({
  unitsQuery,
  contextQuery,
  unitRows,
  contextRows,
  teams,
  selectedEntityId,
  matchFrame,
}: {
  unitsQuery: SeriesQuery;
  contextQuery: SeriesQuery;
  unitRows: readonly TacticalRow[];
  contextRows: readonly TacticalRow[];
  teams: TeamContext;
  selectedEntityId: string | null;
  matchFrame: MatchFrameContextValue | null;
}) {
  const state = queryState(unitsQuery) ?? queryState(contextQuery);
  if (state) return state;
  return (
    <div className="space-y-3 p-3">
      <section>
        <SectionTitle>Possession and ball context</SectionTitle>
        <SourceContext rows={contextRows} teams={teams} />
      </section>
      <StructureTab query={unitsQuery} rows={unitRows} teams={teams} selectedEntityId={selectedEntityId} matchFrame={matchFrame} />
    </div>
  );
}

function RelationsTab({
  mode,
  setMode,
  selectedEntityId,
  teamId,
  teams,
  edgesQuery,
  trianglesQuery,
  interactionsQuery,
  edges,
  triangles,
  interactions,
  matchFrame,
}: {
  mode: TacticalRelationMode;
  setMode: (mode: TacticalRelationMode) => void;
  selectedEntityId: string | null;
  teamId: string | null;
  teams: TeamContext;
  edgesQuery: SeriesQuery;
  trianglesQuery: SeriesQuery;
  interactionsQuery: SeriesQuery;
  edges: readonly TacticalRow[];
  triangles: readonly TacticalRow[];
  interactions: readonly TacticalRow[];
  matchFrame: MatchFrameContextValue | null;
}) {
  const selectedTeam = teamId ?? teams.order[0] ?? null;
  const buttons: readonly [TacticalRelationMode, string][] = [
    ["off", "Off"],
    ["stable-graph", "Stable graph"],
    ["selected-triangles", "Local triangles"],
    ["attacker-defender", "ATT ↔ DEF"],
  ];
  const selectedEdges = edges.filter((row) => row["stable_edge"] === true && (
    selectedEntityId !== null
      ? row["player_a_id"] === selectedEntityId || row["player_b_id"] === selectedEntityId
      : row["group_id"] === selectedTeam
  ));
  const localTriangles = triangles.filter((row) => row["stable_triangle"] === true && jsonIds(row["triangle_player_ids_json"]).includes(selectedEntityId ?? ""));
  const selectedRelations = interactions.filter((row) => row["attacker_id"] === selectedEntityId);
  const query = mode === "stable-graph" ? edgesQuery : mode === "selected-triangles" ? trianglesQuery : mode === "attacker-defender" ? interactionsQuery : null;
  const state = query ? queryState(query) : null;
  return (
    <div className="space-y-3 p-3">
      <section>
        <SectionTitle>Local relations · exact current frame</SectionTitle>
        <div className="mt-2 flex flex-wrap gap-1">
          {buttons.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)} className={cn("t-control-compact rounded-control border px-2 text-[10px]", mode === value ? "border-accent bg-accent/10 text-text-primary" : "border-border-subtle text-text-muted hover:text-text-secondary")}>{label}</button>
          ))}
        </div>
      </section>
      {state}
      {mode === "off" ? <p className="text-[11px] text-text-muted">Choose a relation to request it and show it on the Field.</p> : null}
      {mode !== "off" && selectedEntityId === null && teamId === null ? <StatePanel state="empty" title="Select a player or team first." detail="Relations are local to the selected object; all-team triangle displays are disabled." /> : null}
      {mode === "stable-graph" && !state ? (
        <section className="space-y-1.5" aria-label="Selected player's stable shape graph">
          {selectedEdges.length === 0 ? <StatePanel state="no_frame" title="No stable local edge at this frame." className="min-h-16 p-2" /> : selectedEdges.map((row) => {
            const a = String(row["player_a_id"] ?? "");
            const b = String(row["player_b_id"] ?? "");
            const id = `shape-edge:${row["group_id"]}:${a}:${b}`;
            return <button key={id} type="button" onClick={() => matchFrame?.selectTacticalObject(id)} className="flex w-full items-center justify-between rounded border border-border-subtle px-2 py-1.5 text-left hover:border-accent"><span className="mono text-[10px] text-text-primary">{a} ↔ {b}</span><span className="mono text-[10px] text-text-muted">{(numberOf(row, "edge_persistence_fraction") ?? 0).toFixed(2)} persistence</span></button>;
          })}
          <p className="text-[10px] text-text-muted">Stable incident Delaunay edges only; persistence is not tactical intent.</p>
        </section>
      ) : null}
      {mode === "selected-triangles" && !state ? (
        <section className="space-y-1.5" aria-label="Selected player's local triangles">
          {selectedEntityId === null ? <StatePanel state="empty" title="Select a player to see local triangles." /> : localTriangles.length === 0 ? <StatePanel state="no_frame" title="No stable triangle containing the selected player at this frame." className="min-h-16 p-2" /> : localTriangles.map((row) => {
            const ids = jsonIds(row["triangle_player_ids_json"]);
            const id = `tactical-triangle:${row["group_id"]}:${ids.join(":")}`;
            return <button key={id} type="button" onClick={() => matchFrame?.selectTacticalObject(id)} className="flex w-full items-center justify-between rounded border border-border-subtle px-2 py-1.5 text-left hover:border-accent"><span className="mono text-[10px] text-text-primary">{ids.join(" · ")}</span><span className="mono text-[10px] text-text-muted">{formatValue(numberOf(row, "area_m2"), "m²")} · {String(row["zone"] ?? "zone unavailable")}</span></button>;
          })}
          <p className="text-[10px] text-text-muted">Only stable triangles incident to the selected player are exposed.</p>
        </section>
      ) : null}
      {mode === "attacker-defender" && !state ? (
        <section className="space-y-1.5" aria-label="Selected attacker's nearest defenders">
          {selectedEntityId === null ? <StatePanel state="empty" title="Select an ATT player to see nearest defenders." /> : selectedRelations.length === 0 ? <StatePanel state="no_frame" title="No ATT ↔ DEF relation for this selected player at this frame." className="min-h-16 p-2" /> : selectedRelations.map((row) => {
            const attacker = String(row["attacker_id"] ?? "");
            const defender = String(row["nearest_defender_id"] ?? "");
            const id = `attacker-defender:${attacker}:${defender}`;
            return <button key={id} type="button" onClick={() => { matchFrame?.selectTacticalObject(id); matchFrame?.selectTrackingObject(defender, "player"); }} className="flex w-full items-center justify-between rounded border border-border-subtle px-2 py-1.5 text-left hover:border-accent"><span className="mono text-[10px] text-text-primary">{attacker} → {defender}</span><span className="mono text-[10px] text-text-muted">{formatValue(numberOf(row, "nearest_defender_distance_m"), "m")} · {row["geometric_tie_up"] === true ? "mutual nearest" : "not mutual nearest"}</span></button>;
          })}
          <p className="text-[10px] text-text-muted">Nearest geometry only; no marking, pressure, or assignment claim.</p>
        </section>
      ) : null}
    </div>
  );
}

function SpaceTab({
  statusA,
  statusB,
  statusC,
  occupiedArea,
  occupiedRows,
  territory,
  influence,
  territoryRows,
  influenceRows,
  teams,
  scalarMode,
  setScalarMode,
}: {
  statusA: LevelStatus;
  statusB: LevelStatus;
  statusC: LevelStatus;
  occupiedArea: SeriesQuery;
  occupiedRows: readonly TacticalRow[];
  territory: SeriesQuery;
  influence: SeriesQuery;
  territoryRows: readonly TacticalRow[];
  influenceRows: readonly TacticalRow[];
  teams: TeamContext;
  scalarMode: ScalarFieldMode;
  setScalarMode: (mode: ScalarFieldMode) => void;
}) {
  return (
    <div className="space-y-4 p-3">
      <section aria-label="Occupied area">
        <SectionTitle>Occupied area · optional convex hull</SectionTitle>
        {statusA.kind !== "available" ? (
          <LevelState level="A" status={statusA} />
        ) : (
          queryState(occupiedArea) ?? (
            byTeam(occupiedRows, teams.order).length === 0 ? (
              <StatePanel state="no_frame" title="No occupied-area hull at this frame." className="min-h-16 p-2" />
            ) : (
              <>
                <TeamTable teams={teams} rows={byTeam(occupiedRows, teams.order)} caption="Optional convex-hull area at the current frame" metrics={[{ key: "hull_area_m2", label: "Hull area", unit: "m²" }]} />
                <ClassLine measurementClass={occupiedArea.data?.meta.measurement_class ?? "PIPELINE_DERIVED"} method="Deterministic convex-hull area; an optional occupied-area summary, not the default team shape." />
              </>
            )
          )
        )}
      </section>
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
        <div className="flex items-center justify-between gap-2">
          <SectionTitle>Influence · arrival-time model (Level C)</SectionTitle>
          <label className="flex items-center gap-1 text-[10px] text-text-muted">Field
            <select aria-label="Scalar field mode" value={scalarMode} onChange={(event) => setScalarMode(event.target.value as ScalarFieldMode)} className="rounded border border-border-subtle bg-surface-2 px-1 py-0.5 text-[10px] text-text-primary">
              <option value="heatmap">Heatmap</option>
              <option value="contour">Contour</option>
              <option value="elevation">Analytical elevation</option>
            </select>
          </label>
        </div>
        {statusC.kind !== "available" ? (
          <LevelState level="C" status={statusC} />
        ) : (
          queryState(influence) ?? (
            byTeam(influenceRows, teams.order).length === 0 ? (
              <StatePanel state="no_frame" title="No influence summary at this frame." className="min-h-16 p-2" />
            ) : (
              <>
                <TeamTable teams={teams} rows={byTeam(influenceRows, teams.order)} caption="Level C influence share at the current frame" metrics={[{ key: "influence_percentage", label: "Grid share", unit: "%" }]} />
                <ClassLine measurementClass={influence.data?.meta.measurement_class ?? "MODEL_ESTIMATED"} method={scalarMode === "elevation" ? `ANALYTICAL ELEVATION · NOT PHYSICAL HEIGHT · ${describeElevationSpec(ARRIVAL_TIME_ELEVATION_SPEC)}` : "Versioned kinematic arrival-time assumptions; not measured territory."} />
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

function ReportTab({ payload, datasetId, sessionId, compact = false }: { payload: Record<string, unknown>; datasetId: string; sessionId: string; compact?: boolean }) {
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
      <pre data-testid="tactical-report" tabIndex={0} aria-label="Tactical report JSON" className={`mono mt-3 ${compact ? "max-h-40" : "max-h-[28rem]"} overflow-auto rounded-control border border-border-subtle bg-surface-0 p-2 text-[10px] text-text-muted`}>{text}</pre>
    </div>
  );
}

export type { TacticalCapabilityView };
