/**
 * World context publishers.
 *
 * Each World route publishes the readable projection of its URL-owned
 * context — sport, competition, edition, contest, period/trial and selected
 * player/subject — plus the three readiness facts, into the shell spine and
 * the recent-context list. Names come only from queries the World already
 * issues (or tiny metadata lookups); an unresolved name is published as
 * `pending`, never as the previous World's value.
 */

import { useQuery } from "@tanstack/react-query";

import type { SessionDetail } from "@/api/types";
import {
  basketballSpatialGameQuery,
  datasetsQuery,
  gameEditionsQuery,
  gameQuery,
  seasonEditionsQuery,
  seasonRowsQuery,
} from "@/lib/api/queries";
import { useArtifactsLoadState, useKeyLoadState } from "@/lib/browser-cache";
import { contestTitle, editionTitle, readinessOf, shortDatasetName } from "@/lib/catalog-model";
import { participantLabels } from "@/lib/participants";
import { FAMILY_ORDER, shortTeamName } from "@/lib/season-model";
import type { BasketballSpatialSearch, GameSearch, LabSearch, SeasonSearch } from "@/lib/search";
import { usePublishContext, type Crumb } from "@/lib/state/context";
import { METADATA_STALE_MS, useCatalog } from "@/lib/use-catalog";
import { editionTarget, isPerformanceDomain, studyTarget, teamTarget } from "@/lib/worlds";

function sportCrumb(sportId: string | null | undefined, sportName: string | null | undefined): Crumb[] {
  if (!sportId) return [];
  return [{ key: "sport", label: sportName ?? sportId, kind: "Sport", target: { to: "/data", search: { domain: "sports", sport: sportId } } }];
}

function editionCrumb(editionId: string | null | undefined, label: string | null | undefined): Crumb[] {
  if (!editionId) return [];
  return [{ key: "edition", label: label ?? "Edition", kind: "Competition edition", target: editionTarget(editionId), pending: !label }];
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Match World (`/lab` tracking contests) and Performance World (`/lab` trials). */
export function usePublishLabContext({
  datasetId,
  sessionId,
  search,
  session,
}: {
  datasetId: string;
  sessionId: string;
  search: LabSearch;
  session: SessionDetail | undefined;
}): void {
  const catalog = useCatalog();
  const datasets = useQuery({ ...datasetsQuery(), staleTime: METADATA_STALE_MS });
  const dataset = datasets.data?.find((item) => item.dataset_id === datasetId) ?? null;
  const performance = dataset ? isPerformanceDomain(dataset.domain) : search.view === "signals";
  const contest = catalog.resources.find(
    (resource) => resource.resource_kind === "contest" && resource.session_id === sessionId && (resource.dataset_ids ?? []).includes(datasetId),
  ) ?? null;
  const artifactIds = (session?.streams ?? []).flatMap((stream) => stream.sample_artifact_ids);
  const browser = useArtifactsLoadState(artifactIds);
  const trial = session?.trials.find((item) => item.trial_id === search.trial) ?? null;
  const subjectLabel = search.subject
    ? participantLabels(session).get(search.subject) ?? session?.participants.find((item) => item.subject_id === search.subject)?.notes ?? `Subject ${search.subject}`
    : null;

  let crumbs: Crumb[];
  let title: string | undefined;
  let subtitle: string | undefined;
  if (performance) {
    const trialIndex = search.trial ? /-t(\d+)$/u.exec(search.trial)?.[1] : undefined;
    const condition = /condition=([^;]+)/u.exec(trial?.label ?? "")?.[1]?.trim();
    crumbs = [
      { key: "domain", label: "Human Performance", kind: "Domain", target: { to: "/data", search: { domain: "human" } } },
      { key: "study", label: dataset ? shortDatasetName(dataset.name) : datasetId, kind: "Study", target: studyTarget(datasetId), pending: !dataset },
      { key: "session", label: sessionId, kind: "Session", target: studyTarget(datasetId, { session: sessionId }) },
      ...(search.trial ? [{ key: "trial", label: trialIndex ? `T${trialIndex}${condition ? ` · ${condition}` : ""}` : search.trial, kind: "Trial" }] : []),
    ];
    title = `${dataset ? shortDatasetName(dataset.name) : datasetId} · ${sessionId}`;
    subtitle = [search.trial, search.view].filter(Boolean).join(" · ");
  } else {
    const matchLabel = contest ? contestTitle(contest) : session?.session.label ?? null;
    // The spine uses short club names so the volatile tail (period, player)
    // never truncates at 1366 px; recents keep the full title.
    const spineLabel = contest
      ? contestTitle({ ...contest, teams: (contest.teams ?? []).map((team) => ({ ...team, display_name: shortTeamName(team.display_name) })) })
      : matchLabel;
    crumbs = [
      ...(contest ? sportCrumb(contest.sport_id, contest.sport_name) : dataset ? [{ key: "dataset", label: shortDatasetName(dataset.name), kind: "Source" }] : []),
      ...(contest ? editionCrumb(contest.edition_id, contest ? editionTitle(contest) : null) : []),
      { key: "match", label: spineLabel ?? "Match", kind: "Match", pending: spineLabel === null },
      ...(search.trial ? [{ key: "period", label: capitalize(trial?.label ?? search.trial.replace("_", " ")), kind: "Period" }] : []),
      ...(subjectLabel ? [{ key: "player", label: subjectLabel, kind: "Player" }] : []),
    ];
    title = matchLabel ?? undefined;
    subtitle = [contest ? editionTitle(contest) : null, trial?.label ? capitalize(trial.label) : null, subjectLabel].filter(Boolean).join(" · ");
  }
  const readiness = contest ? readinessOf(contest) : null;
  usePublishContext({
    owner: `${performance ? "performance" : "match"}:${datasetId}/${sessionId}`,
    world: performance ? "performance" : "match",
    crumbs,
    title,
    subtitle,
    readiness: {
      upstream: "available",
      server: readiness?.server ?? (session ? "ready" : undefined),
      browser,
    },
  });
}

/** Game World (`/games`): edition → game → period → play. */
export function usePublishGameContext(search: GameSearch): void {
  const editions = useQuery(gameEditionsQuery());
  const edition = editions.data?.find((item) => item.edition_id === search.edition) ?? null;
  const game = useQuery({ ...gameQuery(search.game ?? ""), enabled: Boolean(search.game) });
  const summary = game.data?.summary ?? null;
  const away = summary?.teams.find((team) => team.side === "away");
  const home = summary?.teams.find((team) => team.side === "home");
  const scored = away?.score !== null && away?.score !== undefined && home?.score !== null && home?.score !== undefined;
  const gameLabel = summary && away && home
    ? scored ? `${away.display_name} ${away.score}–${home.score} ${home.display_name}` : `${away.display_name} @ ${home.display_name}`
    : null;
  const period = search.period ? game.data?.periods.find((item) => String(item.number) === search.period) : undefined;
  const team = search.team ? game.data?.teams_by_id[search.team] ?? null : null;
  const plays = useKeyLoadState(["games", "plays", search.game ?? ""]);
  const crumbs: Crumb[] = [
    ...sportCrumb(edition?.sport_id, edition?.sport_name),
    ...editionCrumb(search.edition, edition ? `${edition.competition_name} ${edition.edition_label}` : null),
    ...(search.game ? [{ key: "game", label: gameLabel ?? "Game", kind: "Game", pending: gameLabel === null }] : []),
    ...(period ? [{ key: "period", label: period.label ?? `Period ${period.number}`, kind: "Period" }] : []),
    ...(team && search.team ? [{ key: "team", label: team, kind: "Team", target: teamTarget(search.team, search.edition) }] : []),
  ];
  usePublishContext({
    owner: `game:${search.edition ?? ""}:${search.game ?? ""}`,
    world: "game",
    crumbs,
    title: gameLabel ?? (edition ? `${edition.competition_name} ${edition.edition_label}` : undefined),
    subtitle: edition ? `${edition.competition_name} ${edition.edition_label}${period ? ` · ${period.label}` : ""}` : "",
    readiness: { upstream: "available", server: edition ? "ready" : undefined, browser: plays },
  });
}

/** Season World (`/season`): edition → team → player → metric family. */
export function usePublishSeasonContext(search: SeasonSearch): void {
  const editions = useQuery(seasonEditionsQuery());
  const edition = editions.data?.find((item) => item.edition_id === search.edition) ?? null;
  // Same resolution as SeasonLab: an explicit available family, else the
  // first available one in the product's family order.
  const available = new Set((edition?.families ?? []).map((item) => item.family));
  const family = search.family && available.has(search.family)
    ? search.family
    : FAMILY_ORDER.find((item) => available.has(item)) ?? "";
  const player = useQuery({
    ...seasonRowsQuery({ editionId: search.edition ?? "", family, metrics: [], subjectIds: search.player ? [search.player] : [], limit: 4 }),
    enabled: Boolean(search.edition && search.player && family),
  });
  const row = player.data?.rows[0] ?? null;
  const familyLabel = edition?.families.find((item) => item.family === family)?.label ?? null;
  const crumbs: Crumb[] = [
    ...sportCrumb(edition?.sport_id, edition?.sport_name),
    ...editionCrumb(search.edition, edition ? `${edition.competition_name} ${edition.edition_label}` : null),
    ...(row ? [{ key: "team", label: row.team_name, kind: "Team", target: teamTarget(row.team_id, search.edition) }] : []),
    ...(search.player ? [{ key: "player", label: row?.player_name ?? "Player", kind: "Player", pending: row === null, target: { to: "/data/player/$subjectId", params: { subjectId: search.player }, search: { edition: search.edition ?? "" } } }] : []),
    ...(familyLabel ? [{ key: "family", label: familyLabel, kind: "Metric family" }] : []),
  ];
  usePublishContext({
    owner: `season:${search.edition ?? ""}:${search.player ?? ""}`,
    world: "season",
    crumbs,
    title: row?.player_name ?? (edition ? `${edition.competition_name} ${edition.edition_label}` : undefined),
    subtitle: [edition ? `${edition.competition_name} ${edition.edition_label}` : null, familyLabel].filter(Boolean).join(" · "),
    readiness: { upstream: "available", server: edition ? "ready" : undefined },
  });
}

/** Basketball court (Match World for basketball tracking). */
export function usePublishCourtContext(search: BasketballSpatialSearch): void {
  const game = useQuery({ ...basketballSpatialGameQuery(search.contest ?? ""), enabled: Boolean(search.contest) });
  const detail = game.data?.game ?? null;
  const summary = detail?.summary ?? null;
  const edition = detail?.edition ?? null;
  const home = summary?.teams.find((team) => team.side === "home");
  const away = summary?.teams.find((team) => team.side === "away");
  const label = home && away ? `${home.display_name} ${home.score ?? ""}–${away.score ?? ""} ${away.display_name}` : null;
  const period = search.period ? detail?.periods.find((item) => String(item.number) === search.period) : undefined;
  const player = search.player ? game.data?.players.find((item) => item.subject_id === search.player) : undefined;
  const frames = useKeyLoadState(["basketball", "frames", search.contest ?? ""]);
  usePublishContext({
    owner: `court:${search.contest ?? ""}`,
    world: "match",
    crumbs: [
      ...sportCrumb(edition?.sport_id, edition?.sport_name),
      ...editionCrumb(edition?.edition_id, edition ? `${edition.competition_name} ${edition.edition_label}` : null),
      ...(search.contest ? [{ key: "contest", label: label ?? "Game", kind: "Contest", pending: label === null }] : []),
      ...(period ? [{ key: "period", label: period.label ?? `Q${period.number}`, kind: "Period" }] : []),
      ...(player ? [{ key: "player", label: player.display_name, kind: "Player" }] : []),
    ],
    title: label ?? undefined,
    subtitle: [edition ? `${edition.competition_name} ${edition.edition_label}` : null, "Court tracking", period?.label].filter(Boolean).join(" · "),
    readiness: { upstream: "available", server: game.data ? (game.data.tracking_materialized ? "ready" : "registered") : undefined, browser: frames },
  });
}
