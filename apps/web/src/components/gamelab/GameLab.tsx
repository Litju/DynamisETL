import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Clock3, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";
import type { KeyboardEvent } from "react";

import type {
  GameBoxFamilyView,
  GameBoxView,
  GameDetailView,
  GamePlayView,
  GameSummaryView,
} from "@/api/types";
import { DataTable, type DataTableColumn } from "@/components/table/DataTable";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { KeyValueRow, Panel } from "@/components/common/Panel";
import {
  gameBoxQuery,
  gameEditionsQuery,
  gamePlaysQuery,
  gameQuery,
  gamesQuery,
} from "@/lib/api/queries";
import { ApiError } from "@/lib/api/client";
import { boxValue, clockDirection, clockLabel, gameSport, metricColumns, presentEvent, sourceColumnsFor, sourceName } from "@/components/gamelab/game-model";
import type { GameSearch } from "@/lib/search";

const PAGE_SIZE = 60;

function cleanSearch(search: GameSearch): GameSearch {
  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === "string" && value.length > 0) output[key] = value;
  }
  return output as GameSearch;
}

export function GameLab() {
  const search = useSearch({ from: "/games" });
  const navigate = useNavigate();
  const editionsQuery = useQuery(gameEditionsQuery());
  const editions = useMemo(
    () => (editionsQuery.data ?? []).filter((edition) => gameSport(edition) !== null),
    [editionsQuery.data],
  );
  const edition = editions.find((item) => item.edition_id === search.edition) ?? editions[0] ?? null;
  const offset = search.offset ? Number(search.offset) : 0;

  const update = useCallback(
    (patch: Partial<GameSearch>, replace = false) => {
      void navigate({
        to: "/games",
        search: (previous: GameSearch) => cleanSearch({ ...previous, ...patch }),
        replace,
      });
    },
    [navigate],
  );

  useEffect(() => {
    if (edition && search.edition !== edition.edition_id) {
      update({ edition: edition.edition_id }, true);
    }
  }, [edition, search.edition, update]);

  const games = useQuery({
    ...(edition ? gamesQuery(edition.edition_id, offset) : gamesQuery("", offset)),
    enabled: Boolean(edition),
  });
  const gameId = search.game ?? "";
  const detail = useQuery({ ...gameQuery(gameId), enabled: Boolean(gameId) });

  useEffect(() => {
    if (detail.data && detail.data.edition.edition_id !== search.edition) {
      update({ edition: detail.data.edition.edition_id, offset: undefined }, true);
    }
  }, [detail.data, search.edition, update]);

  useEffect(() => {
    if (!edition || !games.data || search.game || games.data.rows.length === 0) return;
    update(
      {
        edition: edition.edition_id,
        game: games.data.rows[0]!.contest_id,
        offset: String(games.data.offset),
      },
      true,
    );
  }, [edition, games.data, search.game, update]);

  const contextEdition = detail.data?.edition ?? edition;
  const sport = contextEdition ? gameSport(contextEdition) : null;
  const selectedPeriod = search.period ? Number(search.period) : undefined;
  const sourceColumns = sport ? sourceColumnsFor(sport) : [];
  const plays = useQuery({
    ...gamePlaysQuery(gameId, sourceColumns),
    enabled: Boolean(gameId) && detail.isSuccess && sport !== null,
  });
  const allPlays = plays.data?.rows ?? [];
  const playRows = selectedPeriod
    ? allPlays.filter((play) => play.period_number === selectedPeriod)
    : allPlays;
  const grain = search.box ?? "player";
  const box = useQuery({
    ...gameBoxQuery(gameId, grain),
    enabled: Boolean(gameId) && detail.isSuccess,
  });

  useEffect(() => {
    if (
      detail.data &&
      search.period &&
      !detail.data.periods.some((period) => period.number === Number(search.period))
    ) {
      update({ period: undefined, event: undefined, clock: undefined }, true);
    }
  }, [detail.data, search.period, update]);

  if (editionsQuery.isPending) return <LoadingPanel label="Loading NBA and NHL editions" />;
  if (editionsQuery.isError) {
    return <ErrorPanel error={editionsQuery.error} onRetry={() => void editionsQuery.refetch()} />;
  }
  if (!edition) {
    return (
      <StatePanel
        state="not_materialized"
        title="No NBA or NHL game edition is available."
        detail="GameLab opens contest, play-by-play and game box-score data from supported NBA or NHL editions."
      />
    );
  }

  const selectedPlay = playRows.find((play) => play.source_event_id === search.event) ?? null;
  const selectedIndex = selectedPlay
    ? playRows.findIndex((play) => play.source_event_id === selectedPlay.source_event_id)
    : -1;
  const period = detail.data?.periods.find((item) => item.number === selectedPeriod) ?? null;

  const chooseGame = (next: GameSummaryView) =>
    update({
      edition: next.edition_id ?? edition.edition_id,
      game: next.contest_id,
      team: undefined,
      period: undefined,
      clock: undefined,
      event: undefined,
      player: undefined,
      offset: String(offset),
    });

  const choosePlay = (play: GamePlayView) =>
    update({
      period: String(play.period_number),
      clock: clockLabel(play) ?? undefined,
      event: play.source_event_id,
      team: play.team_id ?? undefined,
      player: play.subject_id ?? undefined,
    });

  const movePlay = (direction: -1 | 1) => {
    const next = Math.max(0, Math.min(playRows.length - 1, (selectedIndex < 0 ? 0 : selectedIndex) + direction));
    const play = playRows[next];
    if (play) choosePlay(play);
  };

  const movePeriod = (direction: -1 | 1) => {
    const periods = detail.data?.periods ?? [];
    const current = periods.findIndex((item) => item.number === selectedPeriod);
    const next = Math.max(0, Math.min(periods.length - 1, (current < 0 ? 0 : current) + direction));
    const target = periods[next];
    if (target) update({ period: String(target.number), event: undefined, clock: undefined });
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="gamelab" data-sport={sport ?? ""}>
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-2">
        <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
          <div className="flex items-baseline gap-3">
            <h1 className="t-surface-title">GameLab</h1>
            <span className="t-label">PLAY_BY_PLAY · PLAYER_GAME · TEAM_GAME</span>
          </div>
          <label className="flex flex-col gap-1 text-[10px] text-text-muted">
            Competition edition
            <select
              aria-label="Competition edition"
              value={edition.edition_id}
              onChange={(event) =>
                update({
                  edition: event.currentTarget.value,
                  game: undefined,
                  team: undefined,
                  period: undefined,
                  clock: undefined,
                  event: undefined,
                  player: undefined,
                  q: undefined,
                  offset: "0",
                  box: undefined,
                })
              }
              className="rounded-control border border-border-strong bg-surface-0 px-2 py-1 text-[12px] text-text-primary"
            >
              {editions.map((item) => (
                <option key={item.edition_id} value={item.edition_id}>
                  {item.competition_name} · {item.edition_label}
                </option>
              ))}
            </select>
          </label>
          <span className="ml-auto text-[11px] text-text-muted">
            {contextEdition?.provider ?? edition.provider} · {contextEdition?.measurement_class ?? edition.measurement_class}
          </span>
        </div>
        {contextEdition?.license.local_only ? (
          <div
            role="note"
            aria-label="Local-only source rights"
            className="mt-2 flex items-start gap-2 rounded-control border border-warning/40 bg-warning/5 px-2.5 py-1.5 text-[11px] text-text-secondary"
          >
            <ShieldAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
            <span>
              <strong className="mr-1 text-warning">Local-only source.</strong>
              {contextEdition.license.notice} Redistribution: {contextEdition.license.redistribution}.
            </span>
          </div>
        ) : null}
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(16rem,0.28fr)_minmax(0,0.72fr)] gap-px overflow-hidden bg-border-subtle">
        <Panel
          title="Contest browser"
          bodyClassName="flex flex-col overflow-hidden"
          actions={
            games.data ? (
              <>
                <span className="t-label px-1" aria-live="polite">
                  {games.data.total === 0 ? "0" : `${offset + 1}–${Math.min(offset + games.data.rows.length, games.data.total)}`} / {games.data.total}
                </span>
                <button
                  type="button"
                  aria-label="Previous games page"
                  disabled={offset <= 0}
                  onClick={() => update({ offset: String(Math.max(0, offset - PAGE_SIZE)) })}
                  className="rounded-control p-1 hover:bg-surface-3 disabled:opacity-40"
                >
                  <ChevronLeft size={14} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label="Next games page"
                  disabled={offset + games.data.limit >= games.data.total}
                  onClick={() => update({ offset: String(offset + PAGE_SIZE) })}
                  className="rounded-control p-1 hover:bg-surface-3 disabled:opacity-40"
                >
                  <ChevronRight size={14} aria-hidden="true" />
                </button>
              </>
            ) : null
          }
        >
          <div className="shrink-0 border-b border-border-subtle p-2">
            <label className="flex flex-col gap-1 text-[10px] text-text-muted">
              Filter this page
              <input
                type="search"
                aria-label="Filter contests"
                placeholder="Team or game ID"
                value={search.q ?? ""}
                onChange={(event) => update({ q: event.currentTarget.value || undefined }, true)}
                className="rounded-control border border-border-strong bg-surface-0 px-2 py-1.5 text-[12px] text-text-primary placeholder:text-text-muted"
              />
            </label>
          </div>
          {games.isPending ? (
            <LoadingPanel label="Loading contests" />
          ) : games.isError ? (
            <GameQueryState error={games.error} onRetry={() => void games.refetch()} />
          ) : (
            <ContestTable
              rows={filterGames(games.data.rows, search.q)}
              selectedId={gameId}
              onSelect={chooseGame}
            />
          )}
        </Panel>

        <main className="grid min-h-0 min-w-0 grid-rows-[auto_minmax(14rem,1fr)_minmax(12rem,0.78fr)] gap-px bg-border-subtle" aria-label="Game analysis">
          {detail.isSuccess ? (
            <GameContext
              detail={detail.data}
              allPlays={allPlays}
              playsComplete={plays.data ? plays.data.total === plays.data.rows.length : !plays.isPending}
              period={period}
              selectedPlay={selectedPlay}
              selectedPlayerId={search.player ?? ""}
              selectedTeamId={search.team ?? ""}
              displayClock={selectedPlay ? clockLabel(selectedPlay) : search.clock ?? null}
              onPlayer={(value) => update({ player: value || undefined })}
              onTeam={(value) => update({ team: value || undefined })}
            />
          ) : detail.isPending && gameId ? (
            <LoadingPanel label="Loading game context" />
          ) : detail.isError && gameId ? (
            <GameQueryState error={detail.error} onRetry={() => void detail.refetch()} />
          ) : (
            <StatePanel state="empty" title="Select a contest to open its game context." />
          )}

          <Panel
            title="Play-by-play timeline"
            bodyClassName="flex flex-col overflow-hidden"
            actions={
              detail.data ? (
                <>
                  <button
                    type="button"
                    aria-label="Previous period"
                    disabled={!detail.data.periods.length}
                    onClick={() => movePeriod(-1)}
                    className="rounded-control p-1 hover:bg-surface-3 disabled:opacity-40"
                  >
                    <ChevronLeft size={14} aria-hidden="true" />
                  </button>
                  <label className="sr-only" htmlFor="game-period">Period</label>
                  <select
                    id="game-period"
                    aria-label="Period"
                    value={period ? String(period.number) : ""}
                    onChange={(event) =>
                      update({ period: event.currentTarget.value || undefined, event: undefined, clock: undefined })
                    }
                    className="rounded-control border border-border-strong bg-surface-0 px-1.5 py-1 text-[11px] text-text-primary"
                  >
                    <option value="">All periods</option>
                    {detail.data.periods.map((item) => (
                      <option key={item.contest_period_id} value={item.number}>
                        {periodName(item)} · {item.event_count}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    aria-label="Next period"
                    disabled={!detail.data.periods.length}
                    onClick={() => movePeriod(1)}
                    className="rounded-control p-1 hover:bg-surface-3 disabled:opacity-40"
                  >
                    <ChevronRight size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label="Previous play"
                    disabled={selectedIndex <= 0}
                    onClick={() => movePlay(-1)}
                    className="rounded-control p-1 hover:bg-surface-3 disabled:opacity-40"
                  >
                    <ChevronLeft size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label="Next play"
                    disabled={selectedIndex < 0 || selectedIndex >= playRows.length - 1}
                    onClick={() => movePlay(1)}
                    className="rounded-control p-1 hover:bg-surface-3 disabled:opacity-40"
                  >
                    <ChevronRight size={14} aria-hidden="true" />
                  </button>
                </>
              ) : null
            }
          >
            {detail.isSuccess && plays.isPending ? (
              <LoadingPanel label="Loading this game's plays" />
            ) : plays.isError ? (
              <GameQueryState error={plays.error} onRetry={() => void plays.refetch()} />
            ) : detail.isSuccess && plays.data ? (
              <PlayTimeline
                rows={playRows}
                detail={detail.data}
                selectedEventId={search.event ?? ""}
                onSelect={choosePlay}
                onMove={movePlay}
              />
            ) : (
              <StatePanel state="empty" title="Select a game to load its event timeline." />
            )}
          </Panel>

          <div className="grid min-h-0 grid-cols-2 gap-px bg-border-subtle">
            <BoxScorePanel
              detail={detail.data ?? null}
              sport={sport}
              grain={grain}
              query={box}
              selectedPlayerId={search.player ?? ""}
              selectedTeamId={search.team ?? ""}
              onGrain={(value) => update({ box: value })}
              onPlayer={(row) => {
                const subjectId = row.subject_id;
                const teamId = row.team_id;
                update({
                  player: typeof subjectId === "string" ? subjectId : undefined,
                  team: typeof teamId === "string" ? teamId : undefined,
                });
              }}
              onTeam={(row) => update({ team: typeof row.team_id === "string" ? row.team_id : undefined })}
            />
            <EventDetailPanel
              detail={detail.data ?? null}
              sport={sport}
              play={selectedPlay}
              playerId={search.player ?? ""}
              teamId={search.team ?? ""}
              boxData={box.data ?? null}
            />
          </div>
        </main>
      </div>
    </div>
  );
}

function ContestTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: readonly GameSummaryView[];
  selectedId: string;
  onSelect: (row: GameSummaryView) => void;
}) {
  const columns = useMemo<DataTableColumn<GameSummaryView>[]>(
    () => [
      {
        id: "contest",
        header: "Contest",
        accessor: (row) => row.teams.map((team) => team.display_name).join(" "),
        cell: (row) => {
          const [away, home] = orderedTeams(row);
          return (
            <div className="min-w-0 leading-tight">
              <span className="block truncate">{away?.display_name ?? "Away"} @ {home?.display_name ?? "Home"}</span>
              <span className="mono text-[10px] text-text-muted">{row.provider_game_id ?? row.contest_id}</span>
            </div>
          );
        },
        size: 2,
      },
      {
        id: "score",
        header: "Score",
        accessor: (row) => row.teams.reduce((total, team) => total + (team.score ?? 0), 0),
        cell: (row) => {
          const [away, home] = orderedTeams(row);
          return `${score(home)}–${score(away)}`;
        },
        size: 0.8,
      },
      {
        id: "date",
        header: "Date",
        accessor: (row) => row.scheduled_start_at ?? "",
        cell: (row) => shortDate(row.scheduled_start_at),
        size: 0.9,
      },
    ],
    [],
  );

  return (
    <div className="min-h-0 flex-1">
      <DataTable
        rows={rows}
        columns={columns}
        getRowId={(row) => row.contest_id}
        onRowClick={onSelect}
        selectedRowId={selectedId || null}
        emptyState={<StatePanel state="empty" title="No contests match this page filter." />}
        virtualizeAbove={24}
        rowHeight={48}
        ariaLabel="NBA and NHL contests"
      />
    </div>
  );
}

function GameContext({
  detail,
  allPlays,
  playsComplete,
  period,
  selectedPlay,
  selectedPlayerId,
  selectedTeamId,
  displayClock,
  onPlayer,
  onTeam,
}: {
  detail: GameDetailView;
  allPlays: readonly GamePlayView[];
  playsComplete: boolean;
  period: GameDetailView["periods"][number] | null;
  selectedPlay: GamePlayView | null;
  selectedPlayerId: string;
  selectedTeamId: string;
  displayClock: string | null;
  onPlayer: (value: string) => void;
  onTeam: (value: string) => void;
}) {
  const [away, home] = orderedTeams(detail.summary);
  const players = Object.entries(detail.subjects).sort((left, right) => left[1].localeCompare(right[1]));
  const clockDirectionLabel = clockDirection(selectedPlay);
  const selectedScore = selectedPlay ? eventScore(selectedPlay) : null;
  const pbpFinalScore = playsComplete ? finalPlayScore(allPlays) : null;
  const scoresMatch =
    pbpFinalScore && home?.score !== null && home?.score !== undefined && away?.score !== null && away?.score !== undefined
      ? pbpFinalScore.home === home.score && pbpFinalScore.away === away.score
      : null;

  return (
    <section aria-label="Game context" className="grid grid-cols-[minmax(0,1fr)_minmax(16rem,0.8fr)] items-center gap-3 bg-surface-1 px-3 py-2">
      <div className="min-w-0">
        <div className="mb-1 flex flex-wrap items-center gap-1 text-[10px] text-text-muted">
          <span>{detail.edition.sport_name}</span><ChevronRight size={10} aria-hidden="true" />
          <span>{detail.edition.competition_name}</span><ChevronRight size={10} aria-hidden="true" />
          <span>{detail.edition.edition_label}</span>
          <span className="ml-auto">{detail.summary.venue ?? "Venue not supplied"}</span>
        </div>
        <div className="flex items-center gap-2">
          <TeamScore team={away} side="Away" />
          <span aria-hidden="true" className="t-label">at</span>
          <TeamScore team={home} side="Home" />
          <span className="ml-auto rounded-control border border-border-subtle px-2 py-1 text-[10px] text-text-muted">
            {detail.summary.status ?? (detail.summary.completed ? "Final" : "Scheduled")}
          </span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-text-muted">
          <span>Schedule score · GAME_SUMMARY</span>
          {pbpFinalScore ? (
            <span>· PBP final {pbpFinalScore.home}–{pbpFinalScore.away} · {scoresMatch ? "agrees with schedule" : "differs; schedule score shown"}</span>
          ) : (
            <span>· {playsComplete ? "PBP final score unavailable" : "PBP score not fully loaded"}</span>
          )}
          {selectedScore ? <span>· PBP at selected event {selectedScore.home}–{selectedScore.away}</span> : null}
          <span className="mono ml-auto">Contest {detail.summary.contest_id}</span>
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-end justify-end gap-2">
        <div aria-label="Selected period" className="rounded-control border border-border-subtle px-2 py-1">
          <span className="block text-[10px] text-text-muted">Period</span>
          <span className="text-[11px] text-text-primary">{period ? periodName(period) : "All periods"}</span>
        </div>
        <div aria-label="Source game clock" className="min-w-20 rounded-control border border-border-subtle px-2 py-1">
          <span className="flex items-center gap-1 text-[10px] text-text-muted"><Clock3 size={11} aria-hidden="true" /> Source clock</span>
          <span className="mono text-[12px] text-text-primary">{displayClock ?? "—"}</span>
          {clockDirectionLabel ? <span className="ml-1 text-[9px] text-text-muted">{clockDirectionLabel}</span> : null}
        </div>
        <label className="flex flex-col gap-1 text-[10px] text-text-muted">
          Selected team
          <select
            aria-label="Selected team"
            value={selectedTeamId}
            onChange={(event) => onTeam(event.currentTarget.value)}
            className="max-w-36 rounded-control border border-border-strong bg-surface-0 px-2 py-1 text-[11px] text-text-primary"
          >
            <option value="">None</option>
            {detail.summary.teams.map((team) => <option key={team.team_id} value={team.team_id}>{team.display_name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[10px] text-text-muted">
          Selected player
          <select
            aria-label="Selected player"
            value={selectedPlayerId}
            onChange={(event) => onPlayer(event.currentTarget.value)}
            className="max-w-40 rounded-control border border-border-strong bg-surface-0 px-2 py-1 text-[11px] text-text-primary"
          >
            <option value="">None</option>
            {players.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
      </div>
    </section>
  );
}

function TeamScore({
  team,
  side,
}: {
  team: GameSummaryView["teams"][number] | undefined;
  side: "Away" | "Home";
}) {
  return (
    <div className="flex min-w-0 flex-1 items-center justify-between gap-2 rounded-control border border-border-subtle bg-surface-0 px-2 py-1.5">
      <div className="min-w-0">
        <span className="block text-[9px] uppercase tracking-wide text-text-muted">{side}</span>
        <span className="block truncate text-[12px] font-medium text-text-primary">{team?.display_name ?? "Team unavailable"}</span>
      </div>
      <span className="mono text-[20px] leading-none text-text-primary">{score(team)}</span>
    </div>
  );
}

function PlayTimeline({
  rows,
  detail,
  selectedEventId,
  onSelect,
  onMove,
}: {
  rows: readonly GamePlayView[];
  detail: GameDetailView;
  selectedEventId: string;
  onSelect: (play: GamePlayView) => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const sport = gameSport(detail.edition) ?? "nba";
  const columns = useMemo<DataTableColumn<GamePlayView>[]>(() => [
    {
      id: "period-clock",
      header: "Period / clock",
      accessor: (play) => `${play.period_number} ${clockLabel(play) ?? ""}`,
      cell: (play) => {
        const period = detail.periods.find((candidate) => candidate.number === play.period_number);
        return (
          <div className="min-w-0 leading-tight">
            <span className="block truncate text-[9px] text-text-muted">{periodName(period)}</span>
            <span className="mono text-[11px] text-text-primary">{clockLabel(play) ?? "—"}</span>
          </div>
        );
      },
      size: 0.6,
      sortable: false,
    },
    {
      id: "event",
      header: "Play",
      accessor: (play) => presentEvent(sport, play).label,
      cell: (play) => {
        const presentation = presentEvent(sport, play);
        const period = detail.periods.find((candidate) => candidate.number === play.period_number);
        const clock = clockLabel(play) ?? "—";
        const team = play.team_id ? detail.teams_by_id[play.team_id] : null;
        const player = play.subject_id ? detail.subjects[play.subject_id] : null;
        const selected = selectedEventId === play.source_event_id;
        return (
          <button
            type="button"
            aria-label={`${periodName(period)} ${clock}, ${presentation.label}${team ? `, ${team}` : ""}${player ? `, ${player}` : ""}`}
            aria-pressed={selected}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(play);
            }}
            data-event-id={play.source_event_id}
            data-testid="play-row"
            className="block w-full min-w-0 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
          >
            <span className={`block truncate text-[11px] font-medium ${selected ? "text-text-primary" : "text-text-secondary"}`}>
              {presentation.label}
            </span>
            <span className="block truncate text-[10px] text-text-muted">
              {presentation.description ?? play.provider_event_type}
            </span>
          </button>
        );
      },
      size: 2.2,
      sortable: false,
    },
    {
      id: "team-order",
      header: "Team / sequence",
      accessor: (play) => {
        const team = play.team_id ? detail.teams_by_id[play.team_id] : "";
        return `${team} ${play.sequence_index}`;
      },
      cell: (play) => {
        const team = play.team_id ? detail.teams_by_id[play.team_id] : null;
        return (
          <div className="min-w-0 text-right">
            <span className="block truncate text-[10px] text-text-secondary">{team ?? "—"}</span>
            <span className="mono text-[9px] text-text-muted">{play.sequence_index}</span>
          </div>
        );
      },
      size: 0.7,
      align: "right",
      sortable: false,
    },
  ], [detail, onSelect, selectedEventId, sport]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      onMove(event.key === "ArrowDown" ? 1 : -1);
    }
    if (event.key === "Home" && rows[0]) {
      event.preventDefault();
      onSelect(rows[0]);
    }
    if (event.key === "End" && rows.at(-1)) {
      event.preventDefault();
      onSelect(rows.at(-1)!);
    }
  };

  return (
    <div
      role="group"
      aria-label="Game plays. Use up and down arrows to change the selected play."
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="min-h-0 flex-1 outline-none focus-visible:ring-1 focus-visible:ring-accent"
      data-testid="game-timeline"
    >
      <DataTable
        rows={rows}
        columns={columns}
        getRowId={(play) => play.source_event_id}
        onRowClick={onSelect}
        selectedRowId={selectedEventId || null}
        emptyState={<StatePanel state="empty" title="No plays are available for this period." />}
        virtualizeAbove={100}
        rowHeight={48}
        ariaLabel="Game plays"
      />
    </div>
  );
}

function BoxScorePanel({
  detail,
  sport,
  grain,
  query,
  selectedPlayerId,
  selectedTeamId,
  onGrain,
  onPlayer,
  onTeam,
}: {
  detail: GameDetailView | null;
  sport: ReturnType<typeof gameSport>;
  grain: "player" | "team";
  query: UseQueryResult<GameBoxView>;
  selectedPlayerId: string;
  selectedTeamId: string;
  onGrain: (value: "player" | "team") => void;
  onPlayer: (row: Record<string, unknown>) => void;
  onTeam: (row: Record<string, unknown>) => void;
}) {
  const boxData = query.data;
  const families = boxData?.families ?? [];
  const title = grain === "player" ? "Player box score" : "Team box score";

  return (
    <Panel
      title={title}
      bodyClassName="flex flex-col overflow-hidden"
      actions={
        <div role="group" aria-label="Box score grain" className="flex items-center gap-1">
          <button
            type="button"
            aria-pressed={grain === "player"}
            onClick={() => onGrain("player")}
            className={`rounded-control px-1.5 py-1 text-[10px] ${grain === "player" ? "bg-surface-3 text-text-primary" : "text-text-muted hover:bg-surface-2"}`}
          >Player</button>
          <button
            type="button"
            aria-pressed={grain === "team"}
            onClick={() => onGrain("team")}
            className={`rounded-control px-1.5 py-1 text-[10px] ${grain === "team" ? "bg-surface-3 text-text-primary" : "text-text-muted hover:bg-surface-2"}`}
          >Team</button>
        </div>
      }
    >
      {query.isPending ? (
        <LoadingPanel label="Loading game box score" />
      ) : query.isError ? (
        <GameQueryState error={query.error} onRetry={() => void query.refetch()} />
      ) : !detail ? (
        <StatePanel state="empty" title="Select a game to load its box score." />
      ) : families.length === 0 ? (
        <StatePanel state="not_materialized" title={`No ${grain.toUpperCase()} grain is present for this contest.`} />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto p-2">
          <p className="mb-2 text-[10px] text-text-muted">
            {detail.edition.provider} · provider-reported fields and units · source values are not mapped across sports.
          </p>
          <div className="flex flex-col gap-3">
            {families.map((family) => (
              <BoxFamily
                key={family.family}
                family={family}
                sport={sport ?? "nba"}
                detail={detail}
                selectedPlayerId={selectedPlayerId}
                selectedTeamId={selectedTeamId}
                onPlayer={onPlayer}
                onTeam={onTeam}
              />
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

function BoxFamily({
  family,
  sport,
  detail,
  selectedPlayerId,
  selectedTeamId,
  onPlayer,
  onTeam,
}: {
  family: GameBoxFamilyView;
  sport: NonNullable<ReturnType<typeof gameSport>>;
  detail: GameDetailView;
  selectedPlayerId: string;
  selectedTeamId: string;
  onPlayer: (row: Record<string, unknown>) => void;
  onTeam: (row: Record<string, unknown>) => void;
}) {
  const playerGrain = family.grain_kind === "PLAYER_GAME";
  const availableMetrics = metricColumns(sport, family.family, family.columns);
  const columns = useMemo<DataTableColumn<Record<string, unknown>>[]>(() => {
    const identity: DataTableColumn<Record<string, unknown>> = playerGrain
      ? {
          id: "player",
          header: "Player",
          accessor: (row) => sourceName(row) ?? (typeof row.subject_id === "string" ? detail.subjects[row.subject_id] : "") ?? "",
          cell: (row) => {
            const subject = typeof row.subject_id === "string" ? row.subject_id : "";
            return detail.subjects[subject] ?? sourceName(row) ?? "Player";
          },
          size: 2.5,
        }
      : {
          id: "team",
          header: "Team",
          accessor: (row) => {
            const teamId = typeof row.team_id === "string" ? row.team_id : "";
            return detail.teams_by_id[teamId] ?? sourceName(row) ?? "";
          },
          cell: (row) => {
            const teamId = typeof row.team_id === "string" ? row.team_id : "";
            return detail.teams_by_id[teamId] ?? sourceName(row) ?? "Team";
          },
          size: 2.5,
        };
    return [
      identity,
      ...availableMetrics.map((metric) => ({
        id: metric.key,
        header: metric.label,
        accessor: (row: Record<string, unknown>) => boxValue(row, metric.key),
        cell: (row: Record<string, unknown>) => String(boxValue(row, metric.key) ?? "—"),
        size: 0.65,
        align: "right" as const,
      })),
    ];
  }, [availableMetrics, detail.subjects, detail.teams_by_id, playerGrain]);

  const getRowId = (row: Record<string, unknown>) =>
    String(playerGrain ? row.subject_id ?? row.source__player_id ?? row.source__athlete_id : row.team_id ?? row.source__team_id);
  const selectedRowId = playerGrain ? selectedPlayerId : selectedTeamId;

  return (
    <section aria-label={`${family.family} provider box score`} className="min-w-0">
      <header className="mb-1 flex flex-wrap items-baseline justify-between gap-1">
        <h3 className="t-section text-text-secondary">{familyName(sport, family.family)}</h3>
        <span className="mono text-[9px] text-text-muted">{family.grain_kind} · {family.rows.length} rows</span>
      </header>
      {availableMetrics.length === 0 ? (
        <StatePanel state="unsupported" title={`No ${sport.toUpperCase()} metric fields are recognized for ${family.family}.`} />
      ) : (
        <div className="h-28 min-w-0">
          <DataTable
            rows={family.rows}
            columns={columns}
            getRowId={getRowId}
            onRowClick={playerGrain ? onPlayer : onTeam}
            selectedRowId={selectedRowId || null}
            rowHeight={28}
            virtualizeAbove={28}
            ariaLabel={familyName(sport, family.family)}
            emptyState={<span>No provider rows for this game.</span>}
          />
        </div>
      )}
    </section>
  );
}

function EventDetailPanel({
  detail,
  sport,
  play,
  playerId,
  teamId,
  boxData,
}: {
  detail: GameDetailView | null;
  sport: ReturnType<typeof gameSport>;
  play: GamePlayView | null;
  playerId: string;
  teamId: string;
  boxData: GameBoxView | null;
}) {
  const selectedRow = boxData?.families
    .flatMap((family) => family.rows)
    .find((row) =>
      playerId ? row.subject_id === playerId : teamId ? row.team_id === teamId : false,
    ) ?? null;
  const selectedSourceFields = selectedRow
    ? Object.entries(selectedRow).filter(
        ([key, value]) => key.startsWith("source__") && value !== null && typeof value !== "object",
      )
    : [];
  const presentation = play && sport ? presentEvent(sport, play) : null;
  const teamName = teamId && detail ? detail.teams_by_id[teamId] : null;
  const playerName = playerId && detail ? detail.subjects[playerId] : null;

  return (
    <Panel title="Event and subject detail" bodyClassName="overflow-auto">
      {!detail ? (
        <StatePanel state="empty" title="Select a contest to inspect its source event." />
      ) : play && presentation ? (
        <div className="p-3">
          <div className="mb-2 flex flex-wrap items-baseline gap-2">
            <h3 className="text-[13px] font-medium text-text-primary">{presentation.label}</h3>
            <span className="text-[10px] text-text-muted">{play.provider_event_type}</span>
            <span className="mono ml-auto text-[9px] text-text-muted">event {play.source_event_id}</span>
          </div>
          {presentation.description ? <p className="mb-2 text-[11px] text-text-secondary">{presentation.description}</p> : null}
          {!presentation.schemaMatchesSport ? (
            <StatePanel state="unsupported" title="The event extension does not match this game's sport." detail={`${play.attributes_schema_id}@${play.attributes_schema_version}`} className="min-h-20 p-2" />
          ) : null}
          <dl className="grid grid-cols-2 gap-x-4">
            <KeyValueRow label="Period">{detail.periods.find((item) => item.number === play.period_number)?.label ?? `Period ${play.period_number}`}</KeyValueRow>
            <KeyValueRow label="Source clock" mono>{clockLabel(play) ?? "Not supplied"} · {clockDirection(play) ?? "direction unknown"}</KeyValueRow>
            <KeyValueRow label="Canonical time" mono>{formatCanonicalTime(play.canonical_time_ns)}</KeyValueRow>
            <KeyValueRow label="Sequence" mono>{play.sequence_index}</KeyValueRow>
            <KeyValueRow label="Team">{teamName ?? "Not supplied"}</KeyValueRow>
            <KeyValueRow label="Player">{playerName ?? "Not supplied"}</KeyValueRow>
            <KeyValueRow label="Schema" mono>{play.attributes_schema_id}@{play.attributes_schema_version}</KeyValueRow>
          </dl>
          {presentation.facts.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Sport-specific event attributes">
              {presentation.facts.map((fact) => (
                <span key={fact.label} className="rounded-control border border-border-subtle px-2 py-1 text-[10px] text-text-secondary">
                  <span className="text-text-muted">{fact.label}: </span>{fact.value}
                </span>
              ))}
            </div>
          ) : null}
          {sport === "nhl" ? <NhlOnIce play={play} /> : null}
          {selectedRow && playerName ? (
            <div className="mt-3 border-t border-border-subtle pt-2">
              <h4 className="t-section mb-1 text-text-muted">{playerName} · provider box-score context</h4>
              <div className="grid grid-cols-2 gap-x-4">
                {sport === "nba" && typeof selectedRow.source__starter === "boolean" ? (
                  <KeyValueRow label="Starter recorded">{selectedRow.source__starter ? "Yes" : "No"}</KeyValueRow>
                ) : null}
                {sport === "nba" && typeof selectedRow.source__position_name === "string" ? (
                  <KeyValueRow label="Position">{selectedRow.source__position_name}</KeyValueRow>
                ) : null}
                <KeyValueRow label="Team">{typeof selectedRow.team_id === "string" ? detail.teams_by_id[selectedRow.team_id] ?? "Not mapped" : "Not supplied"}</KeyValueRow>
              </div>
              <details className="mt-2 border-t border-border-subtle pt-2">
                <summary className="cursor-pointer text-[10px] text-text-muted">All provider box fields ({selectedSourceFields.length})</summary>
                <dl className="mt-1 grid grid-cols-2 gap-x-4">
                  {selectedSourceFields.map(([key, value]) => (
                    <KeyValueRow key={key} label={key.replace(/^source__/, "").replaceAll("_", " ")}>{String(value)}</KeyValueRow>
                  ))}
                </dl>
              </details>
            </div>
          ) : null}
          <p className="mt-3 break-all border-t border-border-subtle pt-2 text-[9px] text-text-muted">
            Source: {detail.edition.provider} · {play.attributes_schema_id}@{play.attributes_schema_version} · ContestPeriod {play.contest_period_id}
          </p>
        </div>
      ) : playerId || teamId ? (
        <div className="p-3">
          <h3 className="mb-1 text-[12px] font-medium text-text-primary">{playerName ?? teamName ?? "Selected subject"}</h3>
          {playerName ? <p className="mono text-[9px] text-text-muted">Subject {playerId}</p> : null}
          {teamName ? <p className="mono text-[9px] text-text-muted">Team {teamId}</p> : null}
          {selectedRow ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-[10px] text-text-muted">All provider box fields ({selectedSourceFields.length})</summary>
              <dl className="mt-1 grid grid-cols-2 gap-x-4">
                {selectedSourceFields.map(([key, value]) => (
                  <KeyValueRow key={key} label={key.replace(/^source__/, "").replaceAll("_", " ")}>{String(value)}</KeyValueRow>
                ))}
              </dl>
            </details>
          ) : (
            <p className="text-[11px] text-text-muted">Select a player box-score row to view its provider fields.</p>
          )}
        </div>
      ) : (
        <StatePanel state="empty" title="Select a play, player, or team to inspect source detail." />
      )}
    </Panel>
  );
}

function NhlOnIce({ play }: { play: GamePlayView }) {
  const source = play.source ?? {};
  const home = sourcePlayers(source, "home_on_");
  const away = sourcePlayers(source, "away_on_");
  const homeGoalie = sourceText(source, "home_goalie");
  const awayGoalie = sourceText(source, "away_goalie");
  const participants = [1, 2, 3].flatMap((number) => {
    const name = sourceText(source, `event_player_${number}_name`);
    const role = play.attributes[`event_player_${number}_type`];
    return name ? [{ name, role: typeof role === "string" ? role : `Player ${number}` }] : [];
  });
  if (!home.length && !away.length && !participants.length && !homeGoalie && !awayGoalie) return null;

  return (
    <div className="mt-3 border-t border-border-subtle pt-2" aria-label="NHL source lineup context">
      <h4 className="t-section mb-1 text-text-muted">On-ice at this event · provider source</h4>
      {participants.length ? <p className="mb-1 text-[10px] text-text-secondary">{participants.map(({ role, name }) => `${role}: ${name}`).join(" · ")}</p> : null}
      <div className="grid grid-cols-2 gap-3 text-[10px]">
        <div><span className="text-text-muted">Home ({sourceText(source, "home_skaters") ?? "?"} skaters)</span><p className="text-text-secondary">{home.join(", ") || "Not supplied"}</p><p className="text-text-muted">Goalie: {homeGoalie ?? "Not supplied"}</p></div>
        <div><span className="text-text-muted">Away ({sourceText(source, "away_skaters") ?? "?"} skaters)</span><p className="text-text-secondary">{away.join(", ") || "Not supplied"}</p><p className="text-text-muted">Goalie: {awayGoalie ?? "Not supplied"}</p></div>
      </div>
    </div>
  );
}

function GameQueryState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (error instanceof ApiError && error.state === "rights_restricted") {
    return (
      <StatePanel
        state="rights"
        title="This game payload is blocked by source rights."
        detail={error.message}
      />
    );
  }
  if (error instanceof ApiError && error.status === 404) {
    return <StatePanel state="not_materialized" title={error.message} />;
  }
  return <ErrorPanel error={error} onRetry={onRetry} />;
}

function orderedTeams(game: GameSummaryView): [GameSummaryView["teams"][number] | undefined, GameSummaryView["teams"][number] | undefined] {
  const away = game.teams.find((team) => team.side.toLowerCase() === "away") ?? game.teams[0];
  const home = game.teams.find((team) => team.side.toLowerCase() === "home") ?? game.teams[1];
  return [away, home];
}

function periodName(period: GameDetailView["periods"][number] | undefined): string {
  return period?.label ?? (period ? `Period ${period.number}` : "Period");
}

function score(team: GameSummaryView["teams"][number] | undefined): string {
  return team?.score === null || team?.score === undefined ? "—" : String(team.score);
}

function shortDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function filterGames(rows: readonly GameSummaryView[], query: string | undefined): GameSummaryView[] {
  const text = query?.trim().toLocaleLowerCase();
  if (!text) return [...rows];
  return rows.filter((row) =>
    `${row.provider_game_id ?? ""} ${row.contest_id} ${row.teams.map((team) => team.display_name).join(" ")}`
      .toLocaleLowerCase()
      .includes(text),
  );
}

function eventScore(play: GamePlayView): { home: number; away: number } | null {
  const home = play.attributes.home_score;
  const away = play.attributes.away_score;
  if (typeof home !== "number" || typeof away !== "number") return null;
  return { home, away };
}

function finalPlayScore(plays: readonly GamePlayView[]): { home: number; away: number } | null {
  for (let index = plays.length - 1; index >= 0; index -= 1) {
    const scoreAtPlay = eventScore(plays[index]!);
    if (scoreAtPlay) return scoreAtPlay;
  }
  return null;
}

function formatCanonicalTime(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "Not mapped";
  const seconds = Math.floor(value / 1_000_000_000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function familyName(sport: NonNullable<ReturnType<typeof gameSport>>, family: string): string {
  if (sport === "nba") return family === "player_game" ? "NBA players" : "NBA teams";
  if (family === "skater_game") return "NHL skaters";
  if (family === "goalie_game") return "NHL goalies";
  return "NHL teams";
}

function sourcePlayers(source: Record<string, unknown>, prefix: "home_on_" | "away_on_"): string[] {
  return Array.from({ length: 7 }, (_value, index) => sourceText(source, `${prefix}${index + 1}`)).filter(
    (value): value is string => value !== null,
  );
}

function sourceText(source: Record<string, unknown>, key: string): string | null {
  const value = source[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}
