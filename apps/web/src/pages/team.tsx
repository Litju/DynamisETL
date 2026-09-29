import { useQuery } from "@tanstack/react-query";
import { useParams, useSearch } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { useMemo } from "react";

import type { SeasonRowView } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { ContestListHeader, ContestRow, GameRow } from "@/components/catalog/ContestRows";
import { api, unwrap } from "@/lib/api/client";
import { gameEditionsQuery, seasonEditionsQuery } from "@/lib/api/queries";
import { findEdition, readinessOf } from "@/lib/catalog-model";
import { shortTeamName } from "@/lib/season-model";
import { usePublishContext, type Crumb } from "@/lib/state/context";
import { METADATA_STALE_MS, useCatalog } from "@/lib/use-catalog";
import { editionTarget, gameWorldTarget, playerTarget, seasonWorldTarget } from "@/lib/worlds";
import { primarySeasonFamily, useEditionPlayers } from "@/pages/edition";

export function TeamPage() {
  const { teamId } = useParams({ from: "/data/team/$teamId" });
  const search = useSearch({ from: "/data/team/$teamId" });
  const catalog = useCatalog();
  const seasonEditions = useQuery(seasonEditionsQuery());
  const gameEditions = useQuery(gameEditionsQuery());

  // Authoritative membership: contests that name this canonical team id.
  const contests = useMemo(
    () => catalog.resources.filter((resource) => resource.resource_kind === "contest" && (resource.teams ?? []).some((team) => team.team_id === teamId)),
    [catalog.resources, teamId],
  );
  const editionIds = useMemo(() => [...new Set(contests.map((contest) => contest.edition_id).filter(Boolean) as string[])], [contests]);
  const editionId = search.edition ?? editionIds[0] ?? null;
  const edition = editionId ? findEdition(catalog.tree, editionId) : null;
  const season = seasonEditions.data?.find((item) => item.edition_id === editionId) ?? null;
  const gameEdition = gameEditions.data?.find((item) => item.edition_id === editionId) ?? null;
  const editionContests = useMemo(
    () => contests.filter((contest) => !editionId || contest.edition_id === editionId),
    [contests, editionId],
  );
  const roster = useEditionPlayers(season, Boolean(season), teamId);
  const games = useQuery({
    queryKey: ["games", "team", editionId, teamId] as const,
    enabled: Boolean(gameEdition && editionContests.length === 0),
    staleTime: METADATA_STALE_MS,
    queryFn: async ({ signal }) => unwrap(await api.GET("/api/games", { params: { query: { edition_id: editionId!, team_id: teamId, limit: 120 } }, signal })),
  });

  const name = editionContests.flatMap((contest) => contest.teams ?? []).find((team) => team.team_id === teamId)?.display_name
    ?? roster.data?.rows.find((row) => row.team_id === teamId)?.team_name
    ?? games.data?.rows.flatMap((game) => game.teams).find((team) => team.team_id === teamId)?.display_name
    ?? null;
  const hasSeasonMembership = roster.data?.rows.some((row) => row.team_id === teamId) ?? false;
  const hasGameMembership = games.data?.rows.some((game) => game.teams.some((team) => team.team_id === teamId)) ?? false;
  const hasEditionMembership = editionContests.length > 0 || hasSeasonMembership || hasGameMembership;

  const crumbs: Crumb[] = [
    ...(edition ? [
      { key: "sport", label: edition.sportName, kind: "Sport", target: { to: "/data", search: { domain: "sports", sport: edition.sportId } } },
      { key: "edition", label: `${edition.competitionName} ${edition.label}`, kind: "Edition", target: editionTarget(edition.editionId) },
    ] : []),
    { key: "team", label: name ?? "Team", kind: "Team", pending: name === null },
  ];
  usePublishContext({ owner: `team:${teamId}:${editionId ?? ""}`, world: null, crumbs });

  if (catalog.isError) return <ErrorPanel error={catalog.error} onRetry={catalog.refetch} />;
  if (seasonEditions.isError) return <ErrorPanel error={seasonEditions.error} onRetry={() => void seasonEditions.refetch()} />;
  if (roster.isError) return <ErrorPanel error={roster.error} onRetry={() => void roster.refetch()} />;
  const gamesEnabled = Boolean(gameEdition && editionContests.length === 0);
  const resolving = catalog.isPending || seasonEditions.isPending || (name === null && ((Boolean(season) && roster.isPending) || (gamesEnabled && games.isPending) || gameEditions.isPending));
  if (!resolving && name === null) {
    return <StatePanel state="not_found" title="No authoritative record names this team in the selected edition." detail="Team membership is resolved by the canonical team id in contest, season, or game-summary rows; names never create membership." />;
  }

  const players = dedupePlayers(roster.data?.rows ?? []);
  const readyContests = editionContests.filter((contest) => readinessOf(contest).server === "ready").length;
  const seasonWorldReady = edition?.worlds.some((world) => world.world === "season" && world.ready) ?? false;

  return (
    <Page label={name ?? "Team"}>
      <PageHeader
        kicker={<>{edition ? `${edition.sportName} · ${edition.competitionName} ${edition.label}` : "Team"} · Team</>}
        title={name ?? <span className="d-skeleton inline-block h-9 w-72 align-middle" />}
        meta={
          <span className="text-[12px] text-text-muted">
            {editionContests.length ? `${readyContests} of ${editionContests.length} registered contests ready` : games.data ? `${games.data.total} play-by-play games` : hasSeasonMembership ? "Season membership verified" : ""}
            {players.length ? ` · ${players.length} players in season aggregates` : ""}
          </span>
        }
        actions={
          <>
            {season && editionId && seasonWorldReady ? (
              <AppLink to={seasonWorldTarget(editionId, { team: teamId })} transition className="d-btn">
                <WorldGlyph world="season" size="sm" className="text-accent" /> Season World
              </AppLink>
            ) : null}
            {gameEdition && editionId ? (
              <AppLink to={{ ...gameWorldTarget(editionId), search: { edition: editionId, team: teamId } }} transition className="d-btn">
                <WorldGlyph world="game" size="sm" className="text-accent" /> Game World
              </AppLink>
            ) : null}
          </>
        }
      />

      {editionIds.length > 1 ? (
        <div className="mt-6 flex flex-wrap gap-2">
          {editionIds.map((id) => {
            const node = findEdition(catalog.tree, id);
            return (
              <AppLink key={id} to={{ to: "/data/team/$teamId", params: { teamId }, search: { edition: id } }} className="d-btn" aria-current={id === editionId ? "true" : undefined}>
                {node ? `${node.competitionName} ${node.label}` : id}
              </AppLink>
            );
          })}
        </div>
      ) : null}

      <div className="mt-10 grid grid-cols-12 gap-x-10 gap-y-10">
        <section className="col-span-12 min-[1250px]:col-span-7" aria-labelledby="team-contests">
          <SectionHeader index="01" id="team-contests" title="Contests" detail="Registered contests naming this team" />
          {editionContests.length ? (
            <div className="d-card contest-list overflow-hidden">
              <ContestListHeader />
              <ul className="divide-y divide-border-subtle">
                {editionContests
                  .sort((a, b) => Number(readinessOf(b).server === "ready") - Number(readinessOf(a).server === "ready"))
                  .map((contest) => (
                    <ContestRow key={contest.resource_id} contest={contest} matches={catalog.matchesByContest} gameEditionId={gameEdition ? editionId : null} />
                  ))}
              </ul>
            </div>
          ) : games.data?.rows.length ? (
            <div className="d-card max-h-[32rem] overflow-y-auto">
              {games.data.rows.map((game) => <GameRow key={game.contest_id} game={game} editionId={editionId!} style={{ height: 40 }} />)}
            </div>
          ) : games.data ? (
            <StatePanel className="d-card min-h-40" state="not_materialized" title="No game summaries name this team in this edition." detail="Season roster membership does not establish participation in a game." />
          ) : gameEditions.isPending || (gamesEnabled && games.isPending) ? (
            <LoadingPanel label="Resolving available team contests" />
          ) : gameEditions.isError ? (
            <ErrorPanel error={gameEditions.error} onRetry={() => void gameEditions.refetch()} />
          ) : games.isError ? (
            <ErrorPanel error={games.error} onRetry={() => void games.refetch()} />
          ) : hasEditionMembership ? (
            <StatePanel className="d-card min-h-40" state="not_materialized" title="No registered contests for this team in this edition." detail="A season roster does not imply player participation in any individual match." />
          ) : (
            <StatePanel className="d-card min-h-40" state="not_materialized" title="Contest availability is resolving." detail="Only contests linked to this canonical team id appear here." />
          )}
        </section>
        <section className="col-span-12 min-[1250px]:col-span-5" aria-labelledby="team-roster">
          <SectionHeader index="02" id="team-roster" title="Roster & season data" detail={season ? `${season.provider} · ${primarySeasonFamily(season)?.label ?? "season"} aggregate` : seasonEditions.isPending ? "Resolving season data" : "No season aggregate"} />
          {seasonEditions.isPending ? (
            <LoadingPanel label="Resolving authoritative team season data" />
          ) : season ? (
            <>
            <ul className="mb-3 grid grid-cols-1 gap-1.5">
              {season.families.map((family) => (
                <li key={family.family}>
                  <AppLink to={seasonWorldTarget(season.edition_id, { team: teamId, family: family.family })} transition className="d-card d-card-interactive flex items-center justify-between gap-3 px-3 py-2 text-[11.5px]">
                    <span className="truncate text-text-primary">{family.label}</span>
                    <span className="mono shrink-0 text-text-muted">{family.row_count} rows · Season World</span>
                  </AppLink>
                </li>
              ))}
            </ul>
            {roster.isPending ? (
              <div className="d-card space-y-2 p-4">{[0, 1, 2, 3].map((index) => <div key={index} className="d-skeleton h-6" />)}</div>
            ) : (
              players.length ? (
              <ul className="d-card max-h-[32rem] divide-y divide-border-subtle overflow-y-auto">
                {players.map((player) => (
                  <li key={player.subject_id}>
                    <AppLink to={playerTarget(player.subject_id, editionId)} transition className="d-row group grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_3rem_1rem] items-center gap-3 px-4 py-2 text-[12.5px]">
                      <span className="truncate text-text-primary">{player.player_name}</span>
                      <span className="truncate text-[11.5px] text-text-muted">{player.positions.join(" / ")}</span>
                      <span className="mono text-right text-[11.5px] text-text-secondary" title="Matches in season aggregate">{player.matches}</span>
                      <ArrowRight size={12} aria-hidden="true" className="text-text-faint group-hover:text-accent" />
                    </AppLink>
                  </li>
                ))}
              </ul>
              ) : (
                <StatePanel className="d-card min-h-32" state="not_materialized" title="No player-season rows name this team." detail="The selected edition has season data, but its authoritative roster contains no player rows for this team id." />
              )
            )}
            </>
          ) : (
            <StatePanel className="d-card min-h-40" state="not_materialized" title="No player-season aggregate for this edition." detail="A roster is shown only from an authoritative season aggregate; it is never inferred from names." />
          )}
        </section>
      </div>
    </Page>
  );
}

function dedupePlayers(rows: readonly SeasonRowView[]) {
  const map = new Map<string, { subject_id: string; player_name: string; team: string; positions: string[]; matches: number }>();
  for (const row of rows) {
    const entry = map.get(row.subject_id) ?? { subject_id: row.subject_id, player_name: row.player_name, team: shortTeamName(row.team_name), positions: [], matches: 0 };
    if (!entry.positions.includes(row.position_group)) entry.positions.push(row.position_group);
    entry.matches = Math.max(entry.matches, row.matches ?? 0);
    map.set(row.subject_id, entry);
  }
  return [...map.values()].sort((a, b) => b.matches - a.matches || a.player_name.localeCompare(b.player_name));
}
