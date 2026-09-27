import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Database, ExternalLink, Map as MapIcon, Search } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import type { SessionSummary, SourceCapabilityView, SportsCatalogMatchView } from "@/api/types";
import { StatePanel } from "@/components/common/StatePanel";
import {
  artifactQuery,
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
      className={`rounded-sm border px-1 py-px text-[9px] ${state === "local" ? "border-quality-valid/40 text-quality-valid" : "border-border-strong text-text-muted"}`}
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

  const currentTrial = search.trial ?? activeSession?.trials[0]?.trial_id ?? "";
  const selectedSubject = matchFrame?.selectedPlayerId ?? search.subject ?? "";
  const heading = "Match Navigator";

  if (datasetListQuery.isPending || sportsQuery.isPending) {
    return <StatePanel state="loading" title="Loading sports catalog" />;
  }
  if (datasetListQuery.isError || sportsQuery.isError) {
    return <StatePanel state="error" title="Sports catalog is unavailable." />;
  }

  return (
    <section
      data-testid="match-navigator"
      className={compact ? "flex h-full min-h-0 flex-col" : "mx-auto flex h-full min-h-0 w-full max-w-6xl flex-col px-5 py-4"}
    >
      <header className={compact ? "border-b border-border-subtle px-3 py-2" : "mb-3 border-b border-border-subtle pb-3"}>
        <div className="flex items-center gap-2">
          <MapIcon size={14} aria-hidden="true" className="text-accent" />
          <h1 className={compact ? "t-section" : "text-base font-medium text-text-primary"}>{heading}</h1>
          {routeSessionId ? (
            <span className="ml-auto flex gap-1">
              <button type="button" aria-label="Navigator back" title="Back" onClick={() => window.history.back()} className="rounded-control p-1 text-text-muted hover:bg-surface-2"><ArrowLeft size={13} /></button>
              <button type="button" aria-label="Navigator forward" title="Forward" onClick={() => window.history.forward()} className="rounded-control p-1 text-text-muted hover:bg-surface-2"><ArrowRight size={13} /></button>
            </span>
          ) : null}
        </div>
        {!compact ? <p className="mt-1 text-[11px] text-text-muted">Browse the sports corpus and local readiness. This view reads catalog metadata only.</p> : null}
      </header>

      <div className={compact ? "space-y-2 border-b border-border-subtle p-2" : "grid gap-2 border-b border-border-subtle pb-3 md:grid-cols-5"}>
        <label className="t-label block text-text-muted">Sport
          <select aria-label="Sport" value={filters.sport} onChange={(event) => setHierarchyFilters({ sport: event.target.value, competition: "", edition: "", team: "" })} className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5 text-[11px] text-text-primary">
            <option value="">All sports</option>{sports.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label className="t-label block text-text-muted">Competition
          <select aria-label="Competition" value={filters.competition} onChange={(event) => setHierarchyFilters({ ...filters, competition: event.target.value, edition: "", team: "" })} className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5 text-[11px] text-text-primary">
            <option value="">All competitions</option>{competitionOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label className="t-label block text-text-muted">Season / Edition
          <select aria-label="Season / Edition" value={filters.edition} onChange={(event) => setHierarchyFilters({ ...filters, edition: event.target.value, team: "" })} className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5 text-[11px] text-text-primary">
            <option value="">All editions</option>{editionOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label className="t-label block text-text-muted">Team
          <select aria-label="Team" value={filters.team} onChange={(event) => setHierarchyFilters({ ...filters, team: event.target.value })} className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5 text-[11px] text-text-primary">
            <option value="">All teams</option>{teamOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label className="t-label block text-text-muted">Match
          <select aria-label="Match" value={activeMatch?.key ?? ""} onChange={(event) => { const match = visibleMatches.find((item) => item.key === event.target.value); if (match) void openMatch(match); }} className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5 text-[11px] text-text-primary">
            <option value="">Choose a match</option>{visibleMatches.map((match) => <option key={match.key} value={match.key}>{matchLabel(match)} · {match.competitionName}</option>)}
          </select>
        </label>
      </div>

      <label className={compact ? "block border-b border-border-subtle p-2 text-text-muted" : "my-3 block max-w-xl text-text-muted"}>
        <span className="t-label flex items-center gap-1"><Search size={11} aria-hidden="true" /> Filter matches</span>
        <input value={textFilter} onChange={(event) => setTextFilter(event.target.value)} placeholder="Team, match or source" aria-label="Filter matches" className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5 text-[11px] text-text-primary" />
      </label>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-subtle bg-surface-1 px-3 py-1.5 text-[10px] text-text-muted">
          <span>{visibleMatches.length} matches</span><span>Source capability · local readiness</span>
        </div>
        {visibleMatches.map((match) => {
          const current = match.key === activeMatch?.key;
          const canOpen = Boolean(match.sessionId && match.localCapabilities.includes("TRACKING"));
          return (
            <article key={match.key} data-testid="match-navigator-match" data-match-id={match.providerMatchId} className={`border-b border-border-subtle px-3 py-2 ${current ? "bg-surface-2" : "hover:bg-surface-1"}`}>
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[11px] font-medium text-text-primary">{matchLabel(match)}</div>
                  <div className="mt-0.5 flex flex-wrap gap-x-2 text-[9px] text-text-muted">
                    <span>{match.competitionName}</span><span>{match.editionLabel}</span><span>{match.datasetProvider || match.datasetName}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <span className="rounded-sm border border-border-subtle px-1 py-px text-[9px] text-text-muted">Source · {sourceReadinessText(match.sourceReadiness)}</span>
                    <span className="rounded-sm border border-border-subtle px-1 py-px text-[9px] text-text-muted">Local · {readinessText(match.localReadiness)}</span>
                    <MatchCapabilityBadges match={match} />
                  </div>
                </div>
                {canOpen ? (
                  <button type="button" onClick={() => void openMatch(match)} aria-label={`Open ${matchLabel(match)}`} className="flex shrink-0 items-center gap-1 rounded-control border border-border-strong px-2 py-1 text-[10px] text-text-secondary hover:bg-surface-3">
                    Open <ExternalLink size={10} aria-hidden="true" />
                  </button>
                ) : (
                  <button type="button" onClick={() => { setPrepareKey(match.key); setStatus("No local tracking artifacts are registered. Prepare the match before opening; browsing has not acquired dense data."); }} aria-label={`Prepare ${matchLabel(match)}`} className="flex shrink-0 items-center gap-1 rounded-control border border-border-subtle px-2 py-1 text-[10px] text-text-muted hover:bg-surface-2">
                    <Database size={10} aria-hidden="true" /> Prepare
                  </button>
                )}
              </div>
              {prepareKey === match.key ? <p role="status" className="mt-1 text-[10px] text-quality-warning">Prepare required · local tracking is absent.</p> : null}
            </article>
          );
        })}
        {visibleMatches.length === 0 ? <p className="p-3 text-[11px] text-text-muted">No matches for these filters.</p> : null}
      </div>

      {activeSession ? (
        <section aria-label="Current match context" className={compact ? "shrink-0 space-y-2 border-t border-border-subtle p-2" : "shrink-0 space-y-2 border-t border-border-subtle py-3"}>
          <h2 className="t-section text-text-muted">{activeMatch ? matchLabel(activeMatch) : activeSession.session.label ?? routeSessionId}</h2>
          <label className="t-label block text-text-muted">Period
          <select aria-label="Match period" value={currentTrial} onChange={(event) => void changePeriod(event.target.value)} className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1 text-[10px] text-text-primary">
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
          <label className="t-label block text-text-muted">Player
            <select aria-label="Match player" value={selectedSubject} onChange={(event) => {
              const id = event.currentTarget.value || null;
              if (matchFrame) matchFrame.selectPlayer(id, { origin: "dashboard" });
              else updateSearch({ subject: id ?? undefined });
            }} className="mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1 text-[10px] text-text-primary">
              <option value="">No player selected</option>{activeSession.participants.map((player) => <option key={player.subject_id} value={player.subject_id}>{player.notes ?? player.subject_id}{player.cohort ? ` · ${player.cohort}` : ""}</option>)}
            </select>
          </label>
          <form onSubmit={commitTimestamp} className="grid grid-cols-[1fr_auto] gap-1">
            <label className="t-label col-span-2 text-text-muted">Canonical timestamp · ns
              <input key={`${routeDatasetId}/${routeSessionId}/${search.t_ns ?? ""}`} name="timestamp" defaultValue={search.t_ns ?? ""} inputMode="numeric" aria-label="Canonical timestamp in nanoseconds" placeholder="e.g. 120000000000" className="mono mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1 text-[10px] text-text-primary" />
            </label>
            <button type="submit" className="col-start-2 rounded-control border border-border-strong px-2 py-1 text-[10px] text-text-secondary hover:bg-surface-2">Go</button>
          </form>
          <form onSubmit={commitRange} className="grid grid-cols-2 gap-1">
            <label className="t-label text-text-muted">From · ns<input key={`${routeDatasetId}/${routeSessionId}/from/${search.from_ns ?? ""}`} name="rangeFrom" defaultValue={search.from_ns ?? ""} inputMode="numeric" aria-label="Range start in nanoseconds" className="mono mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1 text-[9px] text-text-primary" /></label>
            <label className="t-label text-text-muted">To · ns<input key={`${routeDatasetId}/${routeSessionId}/to/${search.to_ns ?? ""}`} name="rangeTo" defaultValue={search.to_ns ?? ""} inputMode="numeric" aria-label="Range end in nanoseconds" className="mono mt-1 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1 text-[9px] text-text-primary" /></label>
            <button type="submit" className="rounded-control border border-border-strong px-2 py-1 text-[10px] text-text-secondary hover:bg-surface-2">Apply range</button>
            <button type="button" onClick={() => analysis?.commitRange(null)} className="rounded-control border border-border-subtle px-2 py-1 text-[10px] text-text-muted hover:bg-surface-2">Clear range</button>
          </form>
        </section>
      ) : null}
      {status ? <p role="status" className="shrink-0 border-t border-border-subtle bg-surface-1 px-3 py-2 text-[10px] text-quality-warning">{status}</p> : null}
    </section>
  );
}
