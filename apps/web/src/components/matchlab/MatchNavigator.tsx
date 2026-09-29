import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Database, Map as MapIcon, Search } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import type { SessionSummary, SourceCapabilityView, SportsCatalogMatchView } from "@/api/types";
import { PrepareDialog } from "@/components/catalog/PrepareDialog";
import { ReadinessGlyph } from "@/components/common/Readiness";
import { StatePanel } from "@/components/common/StatePanel";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import {
  artifactQuery,
  catalogReadModelQuery,
  datasetsQuery,
  sessionQuery,
  sessionsQuery,
  sourceCapabilitiesQuery,
  sportsCatalogMatchesQuery,
} from "@/lib/api/queries";
import { canonicalTimeDefault, defaultMatchPlayerId } from "@/lib/defaults";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useMatchFrameContext } from "@/lib/match-frame-context";
import { normalizeLabSearch, type LabSearch } from "@/lib/search";
import { formatNsDecimal, tryParseNs } from "@/lib/time";

interface NavigatorMatch {
  readonly key: string;
  readonly datasetId: string;
  readonly datasetName: string;
  readonly datasetProvider: string;
  readonly sessionId: string | null;
  readonly providerMatchId: string;
  readonly sportId: string;
  readonly sportName: string;
  readonly competitionId: string;
  readonly competitionName: string;
  readonly editionId: string;
  readonly editionLabel: string;
  readonly label: string;
  readonly teams: SportsCatalogMatchView["teams"];
  readonly upstreamCapabilities: readonly string[];
  readonly localCapabilities: readonly string[];
  readonly sourceReadiness: string;
  readonly localReadiness: string;
}

interface HierarchyFilters {
  readonly sport: string;
  readonly competition: string;
  readonly edition: string;
  readonly team: string;
}

const MODALITY_CAPABILITY: Record<string, string> = {
  tracking: "TRACKING",
  pose: "POSE",
  event: "EVENTS",
  phases: "PHASES",
  force: "FORCE",
  imu: "IMU",
  lpt: "LPT",
  gnss: "GNSS",
};

function capabilitiesFor(modalities: readonly string[] | undefined): string[] {
  return [...new Set((modalities ?? []).flatMap((modality) => {
    const capability = MODALITY_CAPABILITY[modality];
    return capability ? [capability] : [];
  }))];
}

function matchLabel(match: Pick<NavigatorMatch, "teams" | "label" | "providerMatchId">): string {
  const home = match.teams.find((team) => team.side === "home");
  const away = match.teams.find((team) => team.side === "away");
  return home && away ? `${home.display_name} vs ${away.display_name}` : match.label || match.providerMatchId;
}

function readinessText(value: string | undefined): string {
  if (value === "READY") return "Ready locally";
  if (value === "PARTIAL") return "Partly materialized";
  if (value === "MATERIALIZED") return "Session materialized";
  if (value === "UPSTREAM_AVAILABLE") return "Available at source";
  return "Not materialized";
}

function sourceReadinessText(value: string): string {
  if (value === "UPSTREAM_AVAILABLE") return "Available at source";
  if (value === "UPSTREAM_FAILED") return "Source failed";
  if (value === "UPSTREAM_UNAVAILABLE") return "Unavailable at source";
  return "Source profile unavailable";
}

function CapabilityBadge({
  label,
  state,
  testId,
}: {
  readonly label: string;
  readonly state: "local" | "source";
  readonly testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className={`rounded-[4px] border px-1.5 py-px text-[10px] ${state === "local" ? "border-[color-mix(in_oklab,var(--d-ready-ready)_45%,transparent)] text-text-secondary" : "border-dashed border-border-subtle text-text-faint"}`}
      title={`${label} ${state === "local" ? "materialized locally" : "available from source"}`}
    >
      {label} · {state}
    </span>
  );
}

function MatchCapabilityBadges({ match }: { readonly match: NavigatorMatch }) {
  const { upstreamCapabilities: upstream, localCapabilities: local } = match;
  return (
    <span className="flex flex-wrap gap-1" aria-label="Source capabilities and local availability">
      {upstream.includes("TRACKING") || local.includes("TRACKING") ? <CapabilityBadge label="Tracking" state={local.includes("TRACKING") ? "local" : "source"} /> : null}
      {upstream.includes("POSE") || local.includes("POSE") ? <CapabilityBadge label="Pose" state={local.includes("POSE") ? "local" : "source"} testId="pose-capability" /> : null}
      {upstream.includes("EVENTS") || local.includes("EVENTS") ? <CapabilityBadge label="Events" state={local.includes("EVENTS") ? "local" : "source"} /> : null}
    </span>
  );
}

/** Metadata-only corpus browser plus URL-backed controls for an open MatchLab session. */
export function MatchNavigator({ compact = false }: { readonly compact?: boolean }) {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const [surface, datasetId, sessionId] = pathname.split("/").filter(Boolean);
  return (
    <MatchNavigatorContent
      key={`${surface === "lab" ? datasetId ?? "" : ""}/${surface === "lab" ? sessionId ?? "" : ""}`}
      compact={compact}
    />
  );
}

function MatchNavigatorContent({ compact }: { readonly compact: boolean }) {
  const location = useRouterState({ select: (state) => state.location });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const analysis = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
  const datasetListQuery = useQuery(datasetsQuery());
  const sportsQuery = useQuery(sportsCatalogMatchesQuery());
  const catalogQuery = useQuery(catalogReadModelQuery());
  const path = location.pathname.split("/").filter(Boolean);
  const routeDatasetId = path[0] === "lab" ? path[1] ?? null : null;
  const routeSessionId = path[0] === "lab" ? path[2] ?? null : null;
  const search = normalizeLabSearch(location.search);
  const [hierarchyFilters, setHierarchyFilters] = useState<HierarchyFilters | null>(null);
  const [textFilter, setTextFilter] = useState("");
  const [prepareKey, setPrepareKey] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const footballDatasets = useMemo(
    () => (datasetListQuery.data ?? []).filter((dataset) => dataset.domain === "football"),
    [datasetListQuery.data],
  );
  const sessionQueries = useQueries({ queries: footballDatasets.map((dataset) => sessionsQuery(dataset.dataset_id)) });
  const sourceQueries = useQueries({ queries: footballDatasets.map((dataset) => sourceCapabilitiesQuery(dataset.dataset_id)) });
  const sessionRows = new Map<string, SessionSummary[]>();
  const sourceRows = new Map<string, SourceCapabilityView[]>();
  footballDatasets.forEach((dataset, index) => {
    sessionRows.set(dataset.dataset_id, sessionQueries[index]?.data ?? []);
    sourceRows.set(dataset.dataset_id, sourceQueries[index]?.data ?? []);
  });

  const matches = (() => {
    const datasetById = new Map(footballDatasets.map((dataset) => [dataset.dataset_id, dataset]));
    const sessionsByDataset = new Map<string, Map<string, SessionSummary>>();
    footballDatasets.forEach((dataset) => {
      sessionsByDataset.set(dataset.dataset_id, new Map((sessionRows.get(dataset.dataset_id) ?? []).map((item) => [item.session_id, item])));
    });
    const semantic = (sportsQuery.data ?? []).map((item): NavigatorMatch => {
      const dataset = datasetById.get(item.dataset_id);
      const session = item.session_id ? sessionsByDataset.get(item.dataset_id)?.get(item.session_id) :
        sessionsByDataset.get(item.dataset_id)?.get(item.provider_match_id);
      return {
        key: `${item.dataset_id}/${item.provider_match_id}`,
        datasetId: item.dataset_id,
        datasetName: dataset?.name ?? item.dataset_id,
        datasetProvider: dataset?.provider ?? "",
        sessionId: item.session_id ?? session?.session_id ?? null,
        providerMatchId: item.provider_match_id,
        sportId: item.sport_id,
        sportName: item.sport_name,
        competitionId: item.competition_id ?? item.dataset_id,
        competitionName: item.competition_name ?? dataset?.name ?? item.dataset_id,
        editionId: item.edition_id ?? item.dataset_id,
        editionLabel: item.edition_label ?? "Source edition",
        label: matchLabel({ teams: item.teams, label: item.label ?? "", providerMatchId: item.provider_match_id }),
        teams: item.teams,
        upstreamCapabilities: item.source_capability?.upstream_capabilities ?? capabilitiesFor(dataset?.modalities),
        localCapabilities: item.source_capability?.local_capabilities ?? capabilitiesFor(dataset?.ingested_modalities),
        sourceReadiness: item.source_capability?.source_readiness ?? (dataset?.modalities.length ? "UPSTREAM_AVAILABLE" : "UNKNOWN"),
        localReadiness: item.source_capability?.local_readiness ?? ((session?.stream_count ?? 0) > 0 ? "MATERIALIZED" : "NOT_MATERIALIZED"),
      };
    });
    const semanticIds = new Set(semantic.flatMap((item) => [
      `${item.datasetId}/${item.providerMatchId}`,
      ...(item.sessionId ? [`${item.datasetId}/${item.sessionId}`] : []),
    ]));
    const fallback: NavigatorMatch[] = [];
    footballDatasets.forEach((dataset) => {
      for (const session of sessionRows.get(dataset.dataset_id) ?? []) {
        if (semanticIds.has(`${dataset.dataset_id}/${session.session_id}`)) continue;
        const source = (sourceRows.get(dataset.dataset_id) ?? []).find(
          (entry) => entry.external_id === `contest:${session.session_id}`,
        ) ?? null;
        fallback.push({
          key: `${dataset.dataset_id}/${session.session_id}`,
          datasetId: dataset.dataset_id,
          datasetName: dataset.name,
          datasetProvider: dataset.provider,
          sessionId: session.session_id,
          providerMatchId: session.session_id,
          sportId: dataset.domain,
          sportName: "Football",
          competitionId: dataset.dataset_id,
          competitionName: dataset.name,
          editionId: dataset.dataset_id,
          editionLabel: "Registered sessions",
          label: session.label ?? session.session_id,
          teams: [],
          upstreamCapabilities: source?.upstream_capabilities ?? capabilitiesFor(dataset.modalities),
          localCapabilities: source?.local_capabilities ?? capabilitiesFor(dataset.ingested_modalities),
          sourceReadiness: source?.source_readiness ?? (dataset.modalities.length ? "UPSTREAM_AVAILABLE" : "UNKNOWN"),
          localReadiness: source?.local_readiness ?? (session.stream_count > 0 ? "MATERIALIZED" : "NOT_MATERIALIZED"),
        });
      }
    });
    return [...semantic, ...fallback].sort((a, b) => {
      const comp = a.competitionName.localeCompare(b.competitionName);
      if (comp !== 0) return comp;
      return matchLabel(a).localeCompare(matchLabel(b));
    });
  })();

  const activeMatch = matches.find(
    (match) => match.datasetId === routeDatasetId && match.sessionId === routeSessionId,
  ) ?? matches.find((match) => match.datasetId === routeDatasetId && match.providerMatchId === routeSessionId) ?? null;
  const sessionQueryResult = useQuery({
    ...sessionQuery(routeDatasetId ?? "", routeSessionId ?? ""),
    enabled: Boolean(routeDatasetId && routeSessionId),
  });
  const activeSession = sessionQueryResult.data;
  const filters = hierarchyFilters ?? {
    sport: activeMatch?.sportId ?? "",
    competition: activeMatch?.competitionId ?? "",
    edition: activeMatch?.editionId ?? "",
    team: "",
  };

  const sports = [...new Map(matches.map((match) => [match.sportId, match.sportName])).entries()];
  const competitions = matches.filter((match) => !filters.sport || match.sportId === filters.sport);
  const competitionOptions = [...new Map(competitions.map((match) => [match.competitionId, match.competitionName])).entries()];
  const editions = matches.filter((match) =>
    (!filters.sport || match.sportId === filters.sport) &&
    (!filters.competition || match.competitionId === filters.competition),
  );
  const editionOptions = [...new Map(editions.map((match) => [match.editionId, match.editionLabel])).entries()];
  const teamMatches = matches.filter((match) =>
    (!filters.sport || match.sportId === filters.sport) &&
    (!filters.competition || match.competitionId === filters.competition) &&
    (!filters.edition || match.editionId === filters.edition),
  );
  const teamOptions = [...new Map(teamMatches.flatMap((match) => match.teams.map((team) => [team.team_id, team.display_name] as const))).entries()]
    .sort((a, b) => a[1].localeCompare(b[1]));
  const visibleMatches = matches.filter((match) => {
    const needle = textFilter.trim().toLowerCase();
    return (!filters.sport || match.sportId === filters.sport) &&
      (!filters.competition || match.competitionId === filters.competition) &&
      (!filters.edition || match.editionId === filters.edition) &&
      (!filters.team || match.teams.some((team) => team.team_id === filters.team)) &&
      (!needle || `${matchLabel(match)} ${match.datasetName} ${match.providerMatchId}`.toLowerCase().includes(needle));
  });

  const openMatch = async (match: NavigatorMatch) => {
    setStatus(null);
    setPrepareKey(null);
    if (!match.sessionId) {
      setPrepareKey(match.key);
      setStatus("This source match has no local session yet. Prepare its metadata and tracking before opening it.");
      return;
    }
    try {
      const session = await queryClient.fetchQuery(sessionQuery(match.datasetId, match.sessionId));
      const tracking = session.streams.find(
        (stream) => stream.modality === "tracking" && stream.sample_artifact_ids.length > 0,
      );
      if (!tracking) {
        setPrepareKey(match.key);
        setStatus("Tracking is not materialized for this match. Prepare local tracking before opening MatchLab.");
        return;
      }
      const trackingArtifact = await queryClient.fetchQuery(artifactQuery(tracking.sample_artifact_ids[0]!));
      const periodId = tracking.trial_id ?? session.trials[0]?.trial_id;
      const pose = session.streams.find(
        (stream) => stream.modality === "pose" && stream.trial_id === (periodId ?? null) && stream.sample_artifact_ids.length > 0,
      );
      const poseArtifact = pose
        ? await queryClient.fetchQuery(artifactQuery(pose.sample_artifact_ids[0]!))
        : undefined;
      const subject = defaultMatchPlayerId(session, poseArtifact, trackingArtifact);
      const poseTime = poseArtifact
        ? canonicalTimeDefault(poseArtifact, { currentNs: null, view: "pose", subjectId: subject })
        : null;
      const time = canonicalTimeDefault(trackingArtifact, {
        currentNs: poseTime,
        view: "matchlab",
        subjectId: subject,
      }) ?? poseTime ?? canonicalTimeDefault(trackingArtifact, {
        currentNs: null,
        view: "matchlab",
        subjectId: subject,
      });
      await navigate({
        to: "/lab/$datasetId/$sessionId",
        params: { datasetId: match.datasetId, sessionId: match.sessionId },
        search: (previous: LabSearch) => ({
          ...previous,
          trial: periodId,
          stream: tracking.stream_id,
          subject: subject ?? undefined,
          t_ns: time === null ? undefined : formatNsDecimal(time),
          from_ns: undefined,
          to_ns: undefined,
          view: "matchlab",
          tactical: "live",
          entity: undefined,
          metric: undefined,
          result: undefined,
          range_ns: undefined,
          compare: undefined,
        }),
        replace: false,
      });
    } catch {
      setStatus("Match metadata could not be loaded. No dense data was fetched.");
    }
  };

  const changePeriod = async (trialId: string) => {
    if (!activeSession || !analysis) return;
    const tracking = activeSession.streams.find(
      (stream) => stream.trial_id === trialId && stream.modality === "tracking" && stream.sample_artifact_ids.length > 0,
    );
    if (!tracking) {
      setStatus("This period is available at source but is not materialized locally. Prepare it before switching.");
      return;
    }
    setStatus(null);
    try {
      const subject = activeSession.participants.some((item) => item.subject_id === search.subject)
        ? search.subject ?? null
        : null;
      const pose = activeSession.streams.find(
        (stream) => stream.trial_id === trialId && stream.modality === "pose" && stream.sample_artifact_ids.length > 0,
      );
      const [trackingArtifact, poseArtifact] = await Promise.all([
        queryClient.fetchQuery(artifactQuery(tracking.sample_artifact_ids[0]!)),
        pose ? queryClient.fetchQuery(artifactQuery(pose.sample_artifact_ids[0]!)) : Promise.resolve(undefined),
      ]);
      const poseTime = poseArtifact
        ? canonicalTimeDefault(poseArtifact, { currentNs: null, view: "pose", subjectId: subject })
        : null;
      const time = canonicalTimeDefault(trackingArtifact, {
        currentNs: poseTime,
        view: "matchlab",
        subjectId: subject,
      }) ?? poseTime ?? canonicalTimeDefault(trackingArtifact, {
        currentNs: null,
        view: "matchlab",
        subjectId: subject,
      });
      void navigate({
        to: "/lab/$datasetId/$sessionId",
        params: { datasetId: routeDatasetId!, sessionId: routeSessionId! },
        search: (previous: LabSearch) => ({
          ...previous,
          trial: trialId,
          stream: tracking.stream_id,
          subject,
          t_ns: time === null ? undefined : formatNsDecimal(time),
          from_ns: undefined,
          to_ns: undefined,
        }),
        replace: false,
      });
    } catch {
      setStatus("Period metadata could not be loaded. The current match context is unchanged.");
    }
  };

  const commitTimestamp = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("timestamp") ?? "");
    const parsed = tryParseNs(value);
    if (parsed === null || !analysis) {
      setStatus("Enter a signed integer canonical timestamp in nanoseconds.");
      return;
    }
    setStatus(null);
    analysis.commitTime(parsed);
  };

  const commitRange = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const fromNs = tryParseNs(String(form.get("rangeFrom") ?? ""));
    const toNs = tryParseNs(String(form.get("rangeTo") ?? ""));
    if (fromNs === null || toNs === null || fromNs > toNs || !analysis) {
      setStatus("Enter an inclusive range with signed integer nanoseconds and start ≤ end.");
      return;
    }
    setStatus(null);
    analysis.commitRange({ fromNs, toNs });
  };

  const updateSearch = (patch: Partial<LabSearch>) => {
    if (!routeDatasetId || !routeSessionId) return;
    void navigate({
      to: "/lab/$datasetId/$sessionId",
      params: { datasetId: routeDatasetId, sessionId: routeSessionId },
      search: (previous: LabSearch) => ({ ...previous, ...patch }),
      replace: false,
    });
  };

  const catalogResource = (match: NavigatorMatch) => (catalogQuery.data?.resources ?? []).find(
    (resource) => resource.resource_kind === "contest" && (resource.dataset_ids ?? []).includes(match.datasetId) &&
      (resource.external_ids ?? []).includes(match.providerMatchId),
  ) ?? null;

  const currentTrial = search.trial ?? activeSession?.trials[0]?.trial_id ?? "";
  const selectedSubject = matchFrame?.selectedPlayerId ?? search.subject ?? "";
  const heading = "Match Navigator";

  if (datasetListQuery.isPending || sportsQuery.isPending) {
    return <StatePanel state="loading" title="Loading sports catalog" />;
  }
  if (datasetListQuery.isError || sportsQuery.isError) {
    return <StatePanel state="error" title="Sports catalog is unavailable." />;
  }

  const selectClass = "d-input mt-1 block w-full pr-2 text-[11.5px]";
  const filtersBlock = (
    <div className={compact ? "grid grid-cols-2 gap-2 px-4 pb-3" : "grid grid-cols-5 gap-3"}>
      <label className="block"><span className="t-kicker">Sport</span><select aria-label="Sport" value={filters.sport} onChange={(event) => setHierarchyFilters({ sport: event.target.value, competition: "", edition: "", team: "" })} className={selectClass}>
          <option value="">All sports</option>{sports.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </label>
      <label className="block"><span className="t-kicker">Competition</span><select aria-label="Competition" value={filters.competition} onChange={(event) => setHierarchyFilters({ ...filters, competition: event.target.value, edition: "", team: "" })} className={selectClass}>
          <option value="">All competitions</option>{competitionOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </label>
      <label className="block"><span className="t-kicker">Season / Edition</span><select aria-label="Season / Edition" value={filters.edition} onChange={(event) => setHierarchyFilters({ ...filters, edition: event.target.value, team: "" })} className={selectClass}>
          <option value="">All editions</option>{editionOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </label>
      <label className="block"><span className="t-kicker">Team</span><select aria-label="Team" value={filters.team} onChange={(event) => setHierarchyFilters({ ...filters, team: event.target.value })} className={selectClass}>
          <option value="">All teams</option>{teamOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </label>
      <label className={compact ? "col-span-2 block" : "block"}><span className="t-kicker">Match</span>
        <select aria-label="Match" value={activeMatch?.key ?? ""} onChange={(event) => { const match = visibleMatches.find((item) => item.key === event.target.value); if (match) void openMatch(match); }} className={selectClass}>
          <option value="">Choose a match</option>{visibleMatches.map((match) => <option key={match.key} value={match.key}>{matchLabel(match)} · {match.competitionName}</option>)}
        </select>
      </label>
    </div>
  );

  const matchList = (
    <ul className={compact ? "divide-y divide-border-subtle" : "d-card divide-y divide-border-subtle overflow-hidden"}>
      {visibleMatches.map((match) => {
        const current = match.key === activeMatch?.key;
        const canOpen = Boolean(match.sessionId && match.localCapabilities.includes("TRACKING"));
        const readiness = match.localReadiness === "READY" || canOpen ? "ready" : match.localReadiness === "PARTIAL" || match.localReadiness === "MATERIALIZED" ? "materialized" : "upstream";
        return (
          <li key={match.key} data-testid="match-navigator-match" data-match-id={match.providerMatchId} data-selected={current} className={`d-row group ${compact ? "px-4 py-2.5" : "px-5 py-3"}`}>
            <div className="flex items-center gap-3">
              <ReadinessGlyph kind={readiness} className="shrink-0" />
              <div className="min-w-0 flex-1">
                <div className={`truncate font-medium text-text-primary ${compact ? "text-[12px]" : "text-[13px]"}`}>{matchLabel(match)}</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px] text-text-muted">
                  <span>{match.competitionName} {match.editionLabel}</span>
                  <span className="text-text-faint">·</span>
                  <span>Source {sourceReadinessText(match.sourceReadiness).toLowerCase()}</span>
                  <span className="text-text-faint">·</span>
                  <span>Local {readinessText(match.localReadiness).toLowerCase()}</span>
                </div>
                <div className="mt-1.5"><MatchCapabilityBadges match={match} /></div>
              </div>
              {canOpen ? (
                <button type="button" onClick={() => void openMatch(match)} aria-label={`Open ${matchLabel(match)}`} className="d-btn shrink-0 border-selected-border text-text-primary">
                  {current ? "Current" : "Open"} <ArrowRight size={12} aria-hidden="true" />
                </button>
              ) : (
                <button type="button" onClick={() => { setPrepareKey(match.key); setStatus("No local tracking artifacts are registered. Prepare the match before opening; browsing has not acquired dense data."); }} aria-label={`Prepare ${matchLabel(match)}`} className="d-btn shrink-0">
                  <Database size={11} aria-hidden="true" /> Prepare
                </button>
              )}
            </div>
            {prepareKey === match.key ? (
              <p role="status" className="mt-2 flex items-center gap-2 text-[11px] text-warning">
                Prepare required · local tracking is absent.
                {catalogResource(match) ? (
                  <PrepareDialog resource={catalogResource(match)!} trigger={<>Show preparation plan</>} />
                ) : null}
              </p>
            ) : null}
          </li>
        );
      })}
      {visibleMatches.length === 0 ? <li className="px-4 py-6 text-center text-[12px] text-text-muted">No matches for these filters.</li> : null}
    </ul>
  );

  const contextBlock = activeSession ? (
    <section aria-label="Current match context" className={compact ? "space-y-3 border-b border-border-subtle px-4 pb-4 pt-1" : "d-card mt-6 space-y-3 p-5"}>
      <div>
        <div className="t-kicker">Current match</div>
        <h2 className="mt-1 truncate text-[13px] font-semibold text-text-primary">{activeMatch ? matchLabel(activeMatch) : activeSession.session.label ?? routeSessionId}</h2>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block"><span className="t-kicker">Period</span><select aria-label="Match period" value={currentTrial} onChange={(event) => void changePeriod(event.target.value)} className={selectClass}>
            {activeSession.trials.map((trial) => {
              const tracking = activeSession.streams.some((stream) => stream.trial_id === trial.trial_id && stream.modality === "tracking" && stream.sample_artifact_ids.length > 0);
              const poseLocal = activeSession.streams.some((stream) => stream.trial_id === trial.trial_id && stream.modality === "pose" && stream.sample_artifact_ids.length > 0);
              const eventsLocal = activeSession.streams.some((stream) => stream.trial_id === trial.trial_id && stream.modality === "event" && stream.sample_artifact_ids.length > 0) || activeMatch?.localCapabilities.includes("EVENTS");
              const poseSource = activeMatch?.upstreamCapabilities.includes("POSE");
              const eventsSource = activeMatch?.upstreamCapabilities.includes("EVENTS");
              return <option key={trial.trial_id} value={trial.trial_id}>{trial.label ?? trial.trial_id} · {tracking ? "Tracking local" : "Prepare"}{poseLocal ? " · Pose local" : poseSource ? " · Pose source" : ""}{eventsLocal ? " · Events local" : eventsSource ? " · Events source" : ""}</option>;
            })}
          </select>
        </label>
        <label className="block"><span className="t-kicker">Player</span><select aria-label="Match player" value={selectedSubject} onChange={(event) => {
            const id = event.currentTarget.value || null;
            if (matchFrame) matchFrame.selectPlayer(id, { origin: "dashboard" });
            else updateSearch({ subject: id ?? undefined });
          }} className={selectClass}>
            <option value="">No player selected</option>{activeSession.participants.map((player) => <option key={player.subject_id} value={player.subject_id}>{player.notes ?? player.subject_id}{player.cohort ? ` · ${player.cohort}` : ""}</option>)}
          </select>
        </label>
      </div>
      <form onSubmit={commitTimestamp} className="grid grid-cols-[1fr_auto] items-end gap-2">
        <label className="block"><span className="t-kicker">Canonical timestamp · ns</span><input key={`${routeDatasetId}/${routeSessionId}/${search.t_ns ?? ""}`} name="timestamp" defaultValue={search.t_ns ?? ""} inputMode="numeric" aria-label="Canonical timestamp in nanoseconds" placeholder="e.g. 120000000000" className="d-input mono mt-1 block w-full text-[11px]" />
        </label>
        <button type="submit" className="d-btn">Go</button>
      </form>
      <form onSubmit={commitRange} className="grid grid-cols-2 gap-2">
        <label className="block"><span className="t-kicker">From · ns</span><input key={`${routeDatasetId}/${routeSessionId}/from/${search.from_ns ?? ""}`} name="rangeFrom" defaultValue={search.from_ns ?? ""} inputMode="numeric" aria-label="Range start in nanoseconds" className="d-input mono mt-1 block w-full text-[11px]" /></label>
        <label className="block"><span className="t-kicker">To · ns</span><input key={`${routeDatasetId}/${routeSessionId}/to/${search.to_ns ?? ""}`} name="rangeTo" defaultValue={search.to_ns ?? ""} inputMode="numeric" aria-label="Range end in nanoseconds" className="d-input mono mt-1 block w-full text-[11px]" /></label>
        <button type="submit" className="d-btn">Apply range</button>
        <button type="button" onClick={() => analysis?.commitRange(null)} className="d-btn d-btn-ghost">Clear range</button>
      </form>
    </section>
  ) : null;

  if (compact) {
    return (
      <section data-testid="match-navigator" className="flex h-full min-h-0 flex-col">
        <header className="shrink-0 px-4 pb-3 pt-4">
          <div className="t-kicker flex items-center gap-2"><MapIcon size={11} aria-hidden="true" className="text-accent" /> Match World</div>
          <div className="mt-1 flex items-center gap-2">
            <h1 className="text-[15px] font-semibold tracking-[-0.015em] text-text-primary">{heading}</h1>
            {routeSessionId ? (
              <span className="ml-auto mr-8 flex gap-1">
                <button type="button" aria-label="Navigator back" title="Back" onClick={() => window.history.back()} className="rounded-control p-1 text-text-muted hover:bg-hover"><ArrowLeft size={13} /></button>
                <button type="button" aria-label="Navigator forward" title="Forward" onClick={() => window.history.forward()} className="rounded-control p-1 text-text-muted hover:bg-hover"><ArrowRight size={13} /></button>
              </span>
            ) : null}
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {contextBlock}
          <div className="pt-3">{filtersBlock}</div>
          <label className="block px-4 pb-3">
            <span className="sr-only">Filter matches</span>
            <span className="relative flex items-center">
              <Search size={12} aria-hidden="true" className="pointer-events-none absolute left-2.5 text-text-muted" />
              <input value={textFilter} onChange={(event) => setTextFilter(event.target.value)} placeholder="Team, match or source" aria-label="Filter matches" className="d-input w-full pl-7" />
            </span>
          </label>
          <div className="flex items-center justify-between border-y border-border-subtle px-4 py-1.5 text-[10.5px] text-text-muted">
            <span>{visibleMatches.length} matches</span><span>Source · local readiness</span>
          </div>
          {matchList}
        </div>
        {status ? <p role="status" className="shrink-0 border-t border-border-subtle px-4 py-2 text-[11px] text-warning">{status}</p> : null}
      </section>
    );
  }

  return (
    <section data-testid="match-navigator" className="d-atmosphere h-full min-h-0 overflow-y-auto">
      <div className="mx-auto w-full max-w-[72rem] px-8 pb-16 pt-9">
        <header className="mb-7">
          <div className="t-kicker mb-3 flex items-center gap-2"><WorldGlyph world="match" size="sm" className="text-accent" /> Match World · entry</div>
          <h1 className="t-display">{heading}</h1>
          <p className="t-lede mt-3 max-w-2xl">Browse the sports corpus and local readiness. This view reads catalog metadata only; a match's dense tracking and Pose load when you open it.</p>
        </header>
        {filtersBlock}
        <label className="mt-4 block max-w-md">
          <span className="sr-only">Filter matches</span>
          <span className="relative flex items-center">
            <Search size={13} aria-hidden="true" className="pointer-events-none absolute left-2.5 text-text-muted" />
            <input value={textFilter} onChange={(event) => setTextFilter(event.target.value)} placeholder="Team, match or source" aria-label="Filter matches" className="d-input w-full pl-8" />
          </span>
        </label>
        <div className="mb-2 mt-6 flex items-center justify-between text-[11px] text-text-muted">
          <span><span className="mono text-text-secondary">{visibleMatches.length}</span> matches</span><span>Source capability · local readiness</span>
        </div>
        {matchList}
        {contextBlock}
        {status ? <p role="status" className="mt-4 text-[11px] text-warning">{status}</p> : null}
      </div>
    </section>
  );
}
