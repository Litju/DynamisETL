import { Tabs } from "@base-ui/react/tabs";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ArrowRight, Search } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";

import type { GamePage, SeasonEditionView, SeasonRowView } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { FilterSelect } from "@/components/common/FilterSelect";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { ReadinessGlyph, ReadinessLadder, ServerReadiness } from "@/components/common/Readiness";
import { ErrorPanel, StatePanel } from "@/components/common/StatePanel";
import { VirtualList } from "@/components/common/VirtualList";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { ContestListHeader, ContestRow, GameRow } from "@/components/catalog/ContestRows";
import { api, unwrap } from "@/lib/api/client";
import { gameEditionsQuery, seasonEditionsQuery, seasonRowsQuery } from "@/lib/api/queries";
import {
  findEdition,
  readinessOf,
  teamsForContests,
  type EditionNode,
} from "@/lib/catalog-model";
import { cn } from "@/lib/cn";
import type { EditionSearch, EditionTab } from "@/lib/search";
import { shortTeamName } from "@/lib/season-model";
import { usePublishContext } from "@/lib/state/context";
import { METADATA_STALE_MS, useCatalog } from "@/lib/use-catalog";
import { playerTarget, seasonWorldTarget, teamTarget } from "@/lib/worlds";

const GAME_PAGE = 200;

/** Bounded, paged play-by-play game summaries for one edition. */
function useEditionGames(editionId: string, enabled: boolean, teamId?: string) {
  return useInfiniteQuery({
    queryKey: ["games", "edition-pages", editionId, teamId ?? null] as const,
    enabled,
    initialPageParam: 0,
    staleTime: METADATA_STALE_MS,
    queryFn: async ({ pageParam, signal }): Promise<GamePage> =>
      unwrap(
        await api.GET("/api/games", {
          params: { query: { edition_id: editionId, limit: GAME_PAGE, offset: pageParam, ...(teamId ? { team_id: teamId } : {}) } },
          signal,
        }),
      ),
    getNextPageParam: (last) => (last.offset + last.rows.length < last.total ? last.offset + last.rows.length : undefined),
  });
}

/** The family whose rows define player identity (Physical covers every player). */
export function primarySeasonFamily(season: SeasonEditionView | null) {
  return season?.families.find((family) => family.family === "physical") ?? season?.families[0] ?? null;
}

/** One SeasonLab family's rows, projected to identity + matches only. */
export function useEditionPlayers(season: SeasonEditionView | null, enabled: boolean, teamId?: string) {
  const family = primarySeasonFamily(season)?.family ?? "";
  return useQuery({
    ...seasonRowsQuery({
      editionId: season?.edition_id ?? "",
      family,
      metrics: [],
      ...(teamId ? { teamId } : {}),
      limit: 1000,
    }),
    enabled: enabled && Boolean(season && family),
  });
}

export function EditionPage() {
  const { editionId } = useParams({ from: "/data/edition/$editionId" });
  const search = useSearch({ from: "/data/edition/$editionId" });
  const navigate = useNavigate();
  const catalog = useCatalog();
  const edition = useMemo(() => findEdition(catalog.tree, editionId), [catalog.tree, editionId]);
  const seasonEditions = useQuery(seasonEditionsQuery());
  const gameEditions = useQuery(gameEditionsQuery());
  const season = seasonEditions.data?.find((item) => item.edition_id === editionId) ?? null;
  const gameEdition = gameEditions.data?.find((item) => item.edition_id === editionId) ?? null;
  const seasonReady = Boolean(edition?.worlds.some((link) => link.world === "season" && link.ready) && season);
  const gameReady = Boolean(edition?.worlds.some((link) => link.world === "game" && link.ready) && gameEdition);
  const contestSource: "catalog" | "games" | "none" = edition?.contests.length ? "catalog" : gameReady ? "games" : "none";
  const tab: EditionTab = search.tab ?? "matches";

  const update = (patch: Partial<EditionSearch>) =>
    void navigate({
      to: "/data/edition/$editionId",
      params: { editionId },
      search: (previous: EditionSearch) => ({ ...previous, ...patch }),
      replace: true,
    });

  usePublishContext({
    owner: `edition:${editionId}`,
    world: null,
    crumbs: edition
      ? [
          { key: "sport", label: edition.sportName, kind: "Sport", target: { to: "/data", search: { domain: "sports", sport: edition.sportId } } },
          { key: "competition", label: edition.competitionName, kind: "Competition" },
          { key: "edition", label: edition.label, kind: "Edition" },
        ]
      : [{ key: "edition", label: "Edition", kind: "Edition", pending: catalog.isPending }],
  });

  if (catalog.isError) return <ErrorPanel error={catalog.error} onRetry={catalog.refetch} />;
  if (catalog.isPending) {
    return (
      <Page label="Competition edition">
        <div className="d-skeleton h-10 w-72" />
        <div className="d-skeleton mt-4 h-4 w-96" />
        <div className="d-skeleton mt-10 h-64 w-full rounded-[10px]" />
      </Page>
    );
  }
  if (!edition) {
    return (
      <StatePanel
        state="not_found"
        title="This competition edition is not in the catalog."
        detail={<AppLink to={{ to: "/data" }} className="text-accent">Browse data</AppLink>}
      />
    );
  }

  const readiness = edition.resource ? readinessOf(edition.resource) : null;
  const resource = edition.resource;
  const teams = teamsForContests(edition.contests);

  return (
    <Page label={`${edition.competitionName} ${edition.label}`}>
      <PageHeader
        kicker={<>{edition.sportName} · Competition edition</>}
        title={<>{edition.competitionName} <span className="font-medium text-text-muted">{edition.label}</span></>}
        meta={
          <>
            <span className="text-[12px] text-text-muted">
              {(resource?.providers ?? edition.contests[0]?.providers ?? []).join(", ")}
              {" · "}
              {(resource?.rights_identifiers ?? edition.contests[0]?.rights_identifiers ?? []).join(", ") || "rights unclear"}
              {resource?.local_only ? " · local-only" : resource?.noncommercial_only ? " · non-commercial" : ""}
            </span>
            {readiness ? (
              <span className="flex items-center gap-2">
                <ReadinessLadder stage={readiness.server} upstream={readiness.upstream} />
                <ServerReadiness stage={readiness.server} upstream={readiness.upstream} />
              </span>
            ) : null}
          </>
        }
        actions={
          <>
            {edition.worlds.filter((link) => link.ready && link.target && link.world !== "match").map((link) => (
              <AppLink key={link.workbench} to={link.target!} transition className="d-btn">
                <WorldGlyph world={link.world} size="sm" className="text-accent" />
                {link.label}
              </AppLink>
            ))}
          </>
        }
      />

      <Tabs.Root value={tab} onValueChange={(value) => update({ tab: value as EditionTab, q: undefined })} className="mt-8">
        <Tabs.List aria-label="Edition context" className="relative flex gap-1 border-b border-border-subtle">
          <EditionTabButton value="matches" label="Matches" count={contestSource === "catalog" ? edition.contests.length : gameEdition?.contest_count ?? null} />
          <EditionTabButton value="teams" label="Teams" count={contestSource === "catalog" ? teams.length : null} />
          <EditionTabButton value="players" label="Players" count={null} disabled={!seasonReady} />
          <EditionTabButton value="season" label="Season data" count={season?.families.length ?? null} disabled={!seasonReady} />
          <Tabs.Indicator className="absolute bottom-[-1px] left-[var(--active-tab-left)] h-[2px] w-[var(--active-tab-width)] rounded-full bg-accent transition-[left,width] duration-panel ease-instrument" />
        </Tabs.List>

        <Tabs.Panel value="matches" className="pt-5 outline-none">
          {contestSource === "catalog" ? (
            <CatalogMatches edition={edition} search={search} update={update} gameEditionId={gameReady ? editionId : null} />
          ) : contestSource === "games" ? (
            <GameMatches editionId={editionId} />
          ) : edition.ready ? (
            <StatePanel
              className="d-card min-h-32"
              state="empty"
              title="This edition's ready grain is not a contest list."
              detail="Its data opens in the World that serves that grain — use the World action above."
            />
          ) : (
            <UpstreamEditionState edition={edition} />
          )}
        </Tabs.Panel>
        <Tabs.Panel value="teams" className="pt-5 outline-none">
          {tab === "teams" ? (
            contestSource === "catalog" ? (
              <TeamGrid teams={teams.map((team) => ({ id: team.teamId, name: team.name, detail: `${team.readyContests}/${team.contests.length} contests ready` }))} editionId={editionId} />
            ) : contestSource === "games" ? (
              <GameTeams editionId={editionId} />
            ) : (
              <UpstreamEditionState edition={edition} />
            )
          ) : null}
        </Tabs.Panel>
        <Tabs.Panel value="players" className="pt-5 outline-none">
          {tab === "players" && seasonReady ? <PlayerTable season={season!} editionId={editionId} search={search} update={update} /> : null}
          {tab === "players" && !seasonReady ? (
            <StatePanel state="not_materialized" title="No player-season grain is materialized for this edition." detail="Players appear here only from an authoritative season aggregate; play-by-play box scores stay inside the Game World." />
          ) : null}
        </Tabs.Panel>
        <Tabs.Panel value="season" className="pt-5 outline-none">
          {season ? <SeasonFamilies season={season} /> : null}
        </Tabs.Panel>
      </Tabs.Root>
    </Page>
  );
}

function EditionTabButton({ value, label, count, disabled = false }: { value: EditionTab; label: string; count: number | null; disabled?: boolean }) {
  return (
    <Tabs.Tab
      value={value}
      disabled={disabled}
      className="flex h-9 items-center gap-2 px-3 text-[12.5px] font-medium text-text-muted outline-none transition-colors duration-quick hover:text-text-secondary data-[active]:text-text-primary data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40"
    >
      {label}
      {count !== null ? <span className="mono text-[10.5px] text-text-faint">{count}</span> : null}
    </Tabs.Tab>
  );
}

function CatalogMatches({
  edition,
  search,
  update,
  gameEditionId,
}: {
  edition: EditionNode;
  search: EditionSearch;
  update: (patch: Partial<EditionSearch>) => void;
  gameEditionId: string | null;
}) {
  const catalog = useCatalog();
  const teams = teamsForContests(edition.contests);
  const needle = search.q?.toLocaleLowerCase().trim() ?? "";
  const rows = edition.contests
    .filter((contest) => !search.team || (contest.teams ?? []).some((team) => team.team_id === search.team))
    .filter((contest) => {
      const ready = readinessOf(contest).server === "ready";
      if (search.status === "ready" && !ready) return false;
      if (search.status === "upstream" && ready) return false;
      return !needle || `${contest.label} ${(contest.teams ?? []).map((team) => team.display_name).join(" ")}`.toLocaleLowerCase().includes(needle);
    })
    .sort((a, b) => {
      const readyDelta = Number(readinessOf(b).server === "ready") - Number(readinessOf(a).server === "ready");
      if (readyDelta) return readyDelta;
      const aDate = catalog.matchesByContest.get(a.contest_id ?? "")?.scheduled_start_at ?? "";
      const bDate = catalog.matchesByContest.get(b.contest_id ?? "")?.scheduled_start_at ?? "";
      return aDate.localeCompare(bDate);
    });
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="relative flex items-center">
          <Search size={13} aria-hidden="true" className="pointer-events-none absolute left-2.5 text-text-muted" />
          <input
            value={search.q ?? ""}
            onChange={(event) => update({ q: event.target.value || undefined })}
            placeholder="Filter matches"
            aria-label="Filter matches"
            className="d-input w-64 pl-8"
          />
        </label>
        <FilterSelect
          label="Team"
          value={search.team ?? ""}
          onChange={(value) => update({ team: value || undefined })}
          options={[{ value: "", label: "All teams" }, ...teams.map((team) => ({ value: team.teamId, label: team.name }))]}
        />
        <FilterSelect
          label="Status"
          value={search.status ?? ""}
          onChange={(value) => update({ status: (value || undefined) as EditionSearch["status"] })}
          options={[{ value: "", label: "Any" }, { value: "ready", label: "Ready server-side" }, { value: "upstream", label: "Upstream only" }]}
        />
        <span className="ml-auto text-[11px] text-text-muted">
          <span className="mono text-text-secondary">{edition.readyContests}</span> ready ·{" "}
          <span className="mono text-text-secondary">{edition.upstreamContests}</span> upstream-only · browsing acquires nothing
        </span>
      </div>
      <div className="d-card contest-list overflow-hidden">
        <ContestListHeader />
        {rows.length ? (
          <ul className="divide-y divide-border-subtle">
            {rows.map((contest) => (
              <ContestRow key={contest.resource_id} contest={contest} matches={catalog.matchesByContest} gameEditionId={gameEditionId} />
            ))}
          </ul>
        ) : (
          <p className="px-5 py-8 text-center text-[12px] text-text-muted">No contest matches these filters.</p>
        )}
      </div>
    </>
  );
}

function GameMatches({ editionId }: { editionId: string }) {
  const games = useEditionGames(editionId, true);
  const rows = useMemo(() => games.data?.pages.flatMap((page) => page.rows) ?? [], [games.data]);
  const total = games.data?.pages[0]?.total ?? 0;
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = games;
  // Bounded continuation: the next page loads only when the viewport nears it.
  const onNearEnd = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);
  if (games.isError) return <ErrorPanel error={games.error} onRetry={() => void games.refetch()} />;
  return (
    <>
      <div className="mb-3 flex items-center justify-between text-[11px] text-text-muted">
        <span>Play-by-play games; further pages load as you scroll ({GAME_PAGE} per page).</span>
        <span><span className="mono text-text-secondary">{rows.length}</span> of {total || "…"} loaded</span>
      </div>
      <VirtualList
        items={rows}
        rowHeight={40}
        getKey={(game) => game.contest_id}
        renderRow={(game, _index, style) => <GameRow game={game} editionId={editionId} style={style} />}
        onNearEnd={onNearEnd}
        ariaLabel="Games"
        className="d-card h-[min(34rem,62vh)]"
      >
        {games.isPending ? <div className="space-y-2 p-4">{[0, 1, 2, 3, 4, 5].map((index) => <div key={index} className="d-skeleton h-7" />)}</div> : null}
      </VirtualList>
    </>
  );
}

function GameTeams({ editionId }: { editionId: string }) {
  const games = useEditionGames(editionId, true);
  const pages = useMemo(() => games.data?.pages ?? [], [games.data]);
  const loaded = pages.reduce((sum, page) => sum + page.rows.length, 0);
  const total = pages[0]?.total ?? 0;
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = games;
  useEffect(() => {
    // Team membership needs every game summary; the Teams tab asks for it explicitly.
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);
  const teams = useMemo(() => {
    const map = new Map<string, { name: string; games: number }>();
    for (const page of pages) for (const game of page.rows) for (const team of game.teams) {
      const entry = map.get(team.team_id) ?? { name: team.display_name, games: 0 };
      entry.games += 1;
      map.set(team.team_id, entry);
    }
    return [...map.entries()].map(([id, entry]) => ({ id, name: entry.name, detail: `${entry.games} games` })).sort((a, b) => a.name.localeCompare(b.name));
  }, [pages]);
  return (
    <>
      <p className="mb-3 text-[11px] text-text-muted">
        Membership from play-by-play game summaries · {loaded < total ? `resolving ${loaded} of ${total} games` : `${total} games`}
      </p>
      <TeamGrid teams={teams} editionId={editionId} />
    </>
  );
}

function TeamGrid({ teams, editionId }: { teams: readonly { id: string; name: string; detail: string }[]; editionId: string }) {
  if (!teams.length) return <div className="space-y-2">{[0, 1, 2].map((index) => <div key={index} className="d-skeleton h-12 rounded-[10px]" />)}</div>;
  return (
    <ul className="grid grid-cols-2 gap-2 min-[1100px]:grid-cols-3 min-[1500px]:grid-cols-4">
      {teams.map((team) => (
        <li key={team.id}>
          <AppLink to={teamTarget(team.id, editionId)} transition className="d-card d-card-interactive group flex items-center justify-between gap-3 px-4 py-3">
            <span className="min-w-0">
              <span className="block truncate text-[13px] font-medium text-text-primary">{team.name}</span>
              <span className="block text-[11px] text-text-muted">{team.detail}</span>
            </span>
            <ArrowRight size={13} aria-hidden="true" className="shrink-0 text-text-faint group-hover:text-accent" />
          </AppLink>
        </li>
      ))}
    </ul>
  );
}

function PlayerTable({
  season,
  editionId,
  search,
  update,
}: {
  season: SeasonEditionView;
  editionId: string;
  search: EditionSearch;
  update: (patch: Partial<EditionSearch>) => void;
}) {
  const rows = useEditionPlayers(season, true, search.team);
  const needle = search.q?.toLocaleLowerCase().trim() ?? "";
  const players = useMemo(() => {
    const byPlayer = new Map<string, SeasonRowView & { positions: string[] }>();
    for (const row of rows.data?.rows ?? []) {
      const key = `${row.subject_id}|${row.team_id}`;
      const existing = byPlayer.get(key);
      if (existing) {
        existing.positions.push(row.position_group);
        existing.matches = Math.max(existing.matches ?? 0, row.matches ?? 0);
      } else {
        byPlayer.set(key, { ...row, positions: [row.position_group] });
      }
    }
    return [...byPlayer.values()]
      .filter((row) => !needle || `${row.player_name} ${row.team_name}`.toLocaleLowerCase().includes(needle))
      .sort((a, b) => a.player_name.localeCompare(b.player_name));
  }, [needle, rows.data]);
  const teams = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of rows.data?.rows ?? []) map.set(row.team_id, row.team_name);
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows.data]);
  if (rows.isError) return <ErrorPanel error={rows.error} onRetry={() => void rows.refetch()} />;
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="relative flex items-center">
          <Search size={13} aria-hidden="true" className="pointer-events-none absolute left-2.5 text-text-muted" />
          <input value={search.q ?? ""} onChange={(event) => update({ q: event.target.value || undefined })} placeholder="Filter players" aria-label="Filter players" className="d-input w-64 pl-8" />
        </label>
        {teams.length ? (
          <FilterSelect
            label="Team"
            value={search.team ?? ""}
            onChange={(value) => update({ team: value || undefined })}
            options={[{ value: "", label: "All teams" }, ...teams.map(([id, name]) => ({ value: id, label: name }))]}
          />
        ) : null}
        <span className="ml-auto text-[11px] text-text-muted">
          Identity from the {primarySeasonFamily(season)?.label ?? "season"} aggregate · <span className="mono text-text-secondary">{players.length}</span> players
        </span>
      </div>
      <div className="d-card overflow-hidden">
        <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_5rem_1rem] gap-4 border-b border-border-subtle px-5 py-2 text-[10.5px] uppercase tracking-[0.08em] text-text-faint">
          <span>Player</span><span>Team</span><span>Position</span><span className="text-right">Matches</span><span />
        </div>
        <VirtualList
          items={players}
          rowHeight={40}
          getKey={(player) => `${player.subject_id}|${player.team_id}`}
          ariaLabel="Players"
          className="h-[min(30rem,56vh)]"
          renderRow={(player, _index, style) => (
            <AppLink
              to={playerTarget(player.subject_id, editionId)}
              transition
              style={style}
              className="d-row group grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_5rem_1rem] items-center gap-4 px-5 text-[12.5px]"
            >
              <span className="truncate text-text-primary">{player.player_name}</span>
              <span className="truncate text-text-secondary">{shortTeamName(player.team_name)}</span>
              <span className="truncate text-text-muted">{[...new Set(player.positions)].join(" / ")}</span>
              <span className="mono text-right text-text-secondary">{player.matches ?? "—"}</span>
              <ArrowRight size={12} aria-hidden="true" className="text-text-faint group-hover:text-accent" />
            </AppLink>
          )}
        >
          {rows.isPending ? <div className="space-y-2 p-4">{[0, 1, 2, 3, 4].map((index) => <div key={index} className="d-skeleton h-7" />)}</div> : null}
        </VirtualList>
      </div>
    </>
  );
}

function SeasonFamilies({ season }: { season: SeasonEditionView }) {
  return (
    <>
      <SectionHeader title="Metric families" detail={`${season.provider} · ${season.measurement_class.replaceAll("_", " ").toLowerCase()} · ${season.inclusion_rule}`} />
      <ul className="grid grid-cols-1 gap-3 min-[1000px]:grid-cols-3">
        {season.families.map((family) => (
          <li key={family.family}>
            <AppLink to={seasonWorldTarget(season.edition_id, { family: family.family })} transition className="d-card d-card-interactive group flex h-full flex-col p-5">
              <div className="flex items-start justify-between">
                <span className="text-[14px] font-semibold tracking-[-0.01em] text-text-primary">{family.label}</span>
                <WorldGlyph world="season" className="text-text-muted group-hover:text-accent" />
              </div>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="mono text-[20px] text-text-primary">{family.row_count}</span>
                <span className="text-[11.5px] text-text-muted">season rows · {family.grain_kind.replace("_", " ").toLowerCase()}</span>
              </div>
              <div className="mt-auto flex items-center justify-between pt-4 text-[11.5px] text-text-muted">
                <span className="mono truncate text-[10px] text-text-faint" title={family.checksum_sha256}>{family.artifact_id}</span>
                <span className="flex shrink-0 items-center gap-1 group-hover:text-accent">Open <ArrowRight size={12} aria-hidden="true" /></span>
              </div>
            </AppLink>
          </li>
        ))}
      </ul>
    </>
  );
}

function UpstreamEditionState({ edition }: { edition: EditionNode }) {
  const readiness = edition.resource ? readinessOf(edition.resource) : null;
  return (
    <div className="d-card flex items-start gap-4 px-6 py-6">
      <ReadinessGlyph kind="upstream" className="mt-1 size-3" />
      <div>
        <p className="text-[13px] text-text-secondary">Upstream available · not registered on this data plane.</p>
        <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-text-muted">
          The provider publishes {(edition.resource?.upstream_capabilities ?? []).map((capability) => capability.toLowerCase().replace("_", "-")).join(", ") || "data"} for this edition.
          {readiness?.preparation ? ` The next deterministic stage is “${readiness.preparation}”; it runs through the rights-gated command-line pipeline, never from browsing.` : ""}
        </p>
        <p className={cn("mt-3 text-[11px] text-text-faint")}>No contests, teams or players are shown until the edition is registered.</p>
      </div>
    </div>
  );
}
