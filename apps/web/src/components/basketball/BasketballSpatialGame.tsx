import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useState } from "react";

import { BasketballCourt } from "@/components/basketball/BasketballCourt";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import type { BasketballSpatialGameView } from "@/api/types";
import {
  basketballEventsQuery,
  basketballFramesQuery,
  basketballSpatialGameQuery,
} from "@/lib/api/queries";
import type { BasketballSpatialSearch } from "@/lib/search";

const FRAME_CHUNK = 125;
const EVENT_PAGE_SIZE = 500;

function cleanSearch(search: BasketballSpatialSearch): BasketballSpatialSearch {
  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === "string" && value.length > 0) output[key] = value;
  }
  return output as BasketballSpatialSearch;
}

export function BasketballSpatialGame() {
  const search = useSearch({ from: "/basketball" });
  return (
    <BasketballSpatialGameContent
      key={[search.contest ?? "", search.period ?? ""].join(":")}
    />
  );
}

function BasketballSpatialGameContent() {
  const search = useSearch({ from: "/basketball" });
  const navigate = useNavigate();
  const contestId = search.contest ?? "";
  const game = useQuery({ ...basketballSpatialGameQuery(contestId), enabled: Boolean(contestId) });
  const [eventOffset, setEventOffset] = useState(0);

  const update = useCallback(
    (patch: Partial<BasketballSpatialSearch>) => {
      void navigate({
        to: "/basketball",
        search: (previous: BasketballSpatialSearch) => cleanSearch({ ...previous, ...patch }),
        replace: true,
      });
    },
    [navigate],
  );

  const availablePeriods = game.data?.periods ?? [];
  const requestedPeriod = Number(search.period) || availablePeriods[0]?.number || 1;
  const period =
    availablePeriods.find((item) => item.number === requestedPeriod) ?? availablePeriods[0] ?? null;
  const selectedPeriod = period?.number ?? 1;
  const requestedFrame =
    search.frame === undefined ? (period?.first_active_frame ?? 0) : Number(search.frame);
  const frameFrom = useMemo(() => {
    if (!period) return requestedFrame;
    return Math.max(
      period.first_frame,
      period.first_frame + Math.floor((requestedFrame - period.first_frame) / FRAME_CHUNK) * FRAME_CHUNK,
    );
  }, [period, requestedFrame]);
  const framePage = useQuery({
    ...basketballFramesQuery(contestId, selectedPeriod, frameFrom, FRAME_CHUNK),
    enabled: Boolean(contestId && game.data?.tracking_materialized && period),
  });
  const frame =
    framePage.data?.rows.find((item) => item.frame_idx === requestedFrame)
    ?? framePage.data?.rows.find((item) => item.frame_idx > requestedFrame)
    ?? framePage.data?.rows[0]
    ?? null;
  const events = useQuery({
    ...basketballEventsQuery(contestId, selectedPeriod, eventOffset, EVENT_PAGE_SIZE),
    enabled: Boolean(contestId && game.data?.events_materialized && period),
  });
  const visibleEvents = events.data?.rows ?? [];
  const selectedEvent = events.data?.rows.find((item) => item.source_event_id === search.event) ?? null;
  const courtEvents = visibleEvents.filter((event) => {
    if (event.source_event_id === selectedEvent?.source_event_id) return true;
    const linkedFrame = event.source_clock?.linked_frame_idx;
    return typeof linkedFrame === "number" && Math.abs(linkedFrame - (frame?.frame_idx ?? 0)) <= 50;
  });

  useEffect(() => {
    if (!period || !game.data?.tracking_materialized) return;
    if (search.period !== String(period.number)) {
      update({ period: String(period.number), frame: String(period.first_active_frame) });
    } else if (!search.frame) {
      update({ frame: String(period.first_active_frame) });
    }
  }, [game.data?.tracking_materialized, period, search.frame, search.period, update]);

  if (!contestId) {
    return (
      <StatePanel
        state="empty"
        title="Select a basketball contest in GameLab."
        detail="The court view opens from a catalogued ACB game and keeps its context in the URL."
      />
    );
  }
  if (game.isPending) return <LoadingPanel label="Loading basketball game context" />;
  if (game.isError) return <ErrorPanel error={game.error} onRetry={() => void game.refetch()} />;
  if (!game.data.tracking_materialized || !game.data.periods.length) {
    return (
      <div className="flex h-full min-h-0 flex-col" data-testid="basketball-spatial-game">
        <GameHeader game={game.data} />
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          <StatePanel
            state="not_materialized"
            title="Tracking has not been materialized for this game."
            detail="The metadata catalog stays lightweight. Acquire this game's tracking and Dynamic Events explicitly to open the spatial replay."
          />
        </div>
      </div>
    );
  }

  const firstFrame = period?.first_frame ?? 0;
  const lastFrame = period?.last_frame ?? firstFrame;
  const frameIndex = frame?.frame_idx ?? (Number(search.frame) || firstFrame);
  const roster = game.data.players;

  return (
    <div
      className="basketball-spatial-game flex h-full min-h-0 flex-col"
      data-testid="basketball-spatial-game"
      data-contest-id={contestId}
      data-sport="basketball"
    >
      <GameHeader game={game.data} />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(17rem,0.34fr)] gap-px bg-border-subtle">
        <main className="flex min-h-0 min-w-0 flex-col bg-surface-0">
          <div className="flex flex-wrap items-end gap-3 border-b border-border-subtle bg-surface-1/70 px-4 py-2">
            <label className="flex flex-col gap-1 text-[10px] text-text-muted">
              Period
              <select
                aria-label="Basketball period"
                value={String(selectedPeriod)}
                onChange={(event) =>
                  update({
                    period: event.currentTarget.value,
                    frame: undefined,
                    event: undefined,
                  })
                }
                className="rounded-control border border-border-strong bg-surface-0 px-2 py-1 text-[12px] text-text-primary"
              >
                {availablePeriods.map((item) => (
                  <option key={item.number} value={item.number}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <ClockReadout label="Game clock" value={frame?.game_clock_s} />
            <ClockReadout label="Shot clock" value={frame?.shot_clock_s} />
            <span className="ml-auto text-[10px] text-text-muted" aria-live="polite">
              {frame?.game_clock_stopped ? "Clock stopped" : "Clock running"}
            </span>
          </div>
          <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden p-3 sm:p-6">
            {framePage.isPending ? (
              <LoadingPanel label="Loading tracking frame" />
            ) : framePage.isError ? (
              <ErrorPanel error={framePage.error} onRetry={() => void framePage.refetch()} />
            ) : frame ? (
              <BasketballCourt
                game={game.data}
                frame={frame}
                events={courtEvents}
                selectedEventId={selectedEvent?.source_event_id ?? null}
                selectedPlayerId={search.player ?? null}
                selectedEntity={search.entity ?? null}
                onEvent={(event) => seekToEvent(event)}
                onPlayer={(subjectId) =>
                  update({ player: subjectId, entity: subjectId, event: undefined })
                }
                onBall={() =>
                  update({
                    player: undefined,
                    entity: search.entity === "ball" ? undefined : "ball",
                    event: undefined,
                  })
                }
              />
            ) : (
              <StatePanel state="empty" title="No source frame is available in this period." />
            )}
          </div>
          <div className="border-t border-border-subtle bg-surface-1/70 px-4 py-2">
            <div className="flex items-center gap-2">
              <button
                type="button"
                aria-label="Previous frame"
                disabled={frameIndex <= firstFrame}
                onClick={() => update({ frame: String(Math.max(firstFrame, frameIndex - 1)) })}
                className="rounded-control border border-border-subtle px-2 py-1 text-[11px] disabled:opacity-40"
              >
                ‹
              </button>
              <input
                type="range"
                aria-label="Frame timeline"
                min={firstFrame}
                max={lastFrame}
                value={frameIndex}
                onChange={(event) => update({ frame: event.currentTarget.value, event: undefined })}
                className="min-w-0 flex-1 accent-accent"
              />
              <button
                type="button"
                aria-label="Next frame"
                disabled={frameIndex >= lastFrame}
                onClick={() => update({ frame: String(Math.min(lastFrame, frameIndex + 1)) })}
                className="rounded-control border border-border-subtle px-2 py-1 text-[11px] disabled:opacity-40"
              >
                ›
              </button>
              <span className="mono min-w-24 text-right text-[10px] text-text-muted">
                frame {frame?.frame_idx ?? frameIndex}
              </span>
            </div>
            <p className="mt-1 text-[10px] text-text-muted">
              Source cadence 25 fps · {period?.frame_count.toLocaleString()} frames in {period?.label}
              {frame?.is_dead_time ? " · no tracked positions in this dead-time frame" : ""}
            </p>
          </div>
        </main>

        <aside className="flex min-h-0 flex-col bg-surface-0" aria-label="Basketball game controls">
          <section className="border-b border-border-subtle p-3">
            <label className="flex flex-col gap-1 text-[10px] text-text-muted">
              Selected player
              <select
                aria-label="Selected player"
                value={search.player ?? ""}
                onChange={(event) =>
                  update({
                    player: event.currentTarget.value || undefined,
                    entity: event.currentTarget.value || undefined,
                    event: undefined,
                  })
                }
                className="rounded-control border border-border-strong bg-surface-0 px-2 py-1.5 text-[12px] text-text-primary"
              >
                <option value="">All players</option>
                {roster.map((player) => (
                  <option key={player.subject_id} value={player.subject_id}>
                    #{player.jersey ?? "—"} · {player.display_name}
                  </option>
                ))}
              </select>
            </label>
          </section>
          <section className="flex min-h-0 flex-1 flex-col" aria-labelledby="basketball-events-title">
            <div className="flex items-center gap-2 border-b border-border-subtle px-3 py-2">
              <h2 id="basketball-events-title" className="t-section">Dynamic Events</h2>
              <span className="mono ml-auto text-[10px] text-text-muted">
                {events.data ? `${events.data.total.toLocaleString()} · ${eventOffset + 1}–${Math.min(eventOffset + visibleEvents.length, events.data.total)}` : ""}
              </span>
              <button
                type="button"
                aria-label="Previous event page"
                disabled={eventOffset <= 0}
                onClick={() => setEventOffset(Math.max(0, eventOffset - EVENT_PAGE_SIZE))}
                className="rounded-control border border-border-subtle px-1.5 py-0.5 text-[10px] disabled:opacity-40"
              >
                ‹
              </button>
              <button
                type="button"
                aria-label="Next event page"
                disabled={!events.data || eventOffset + EVENT_PAGE_SIZE >= events.data.total}
                onClick={() => setEventOffset(eventOffset + EVENT_PAGE_SIZE)}
                className="rounded-control border border-border-subtle px-1.5 py-0.5 text-[10px] disabled:opacity-40"
              >
                ›
              </button>
            </div>
            {events.isPending ? (
              <LoadingPanel label="Loading source events" />
            ) : events.isError ? (
              <ErrorPanel error={events.error} onRetry={() => void events.refetch()} />
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto">
                {visibleEvents.map((event) => {
                  const linkedFrame = event.source_clock?.linked_frame_idx;
                  const canSeek = typeof linkedFrame === "number";
                  const selected = event.source_event_id === search.event;
                  const location = event.location;
                  const locationLabel =
                    location && typeof location.x === "number" && typeof location.y === "number"
                      ? `${location.x.toFixed(1)}, ${location.y.toFixed(1)} ft`
                      : "No source location";
                  return (
                    <button
                      key={`${event.provider_event_type}:${event.source_event_id}:${event.sequence_index}`}
                      type="button"
                      data-testid="basketball-event"
                      data-event-id={event.source_event_id}
                      aria-pressed={selected}
                      disabled={!canSeek}
                      onClick={() => seekToEvent(event)}
                      className={`flex w-full items-start gap-2 border-b border-border-subtle px-3 py-2 text-left hover:bg-surface-1 disabled:cursor-default disabled:opacity-60 ${selected ? "bg-surface-2" : ""}`}
                    >
                      <span className="mono mt-0.5 w-16 shrink-0 text-[10px] text-text-muted">
                        {formatClock(event.source_clock?.game_clock_s)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[11px] font-medium text-text-primary">
                          {event.provider_event_type.replaceAll("_", " ")}
                        </span>
                        <span className="block truncate text-[10px] text-text-muted">
                          {locationLabel}
                          {canSeek ? ` · frame ${linkedFrame}` : " · no exact frame key"}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
          <footer className="flex flex-wrap items-center gap-2 border-t border-border-subtle p-3">
            <button
              type="button"
              onClick={() =>
                void navigate({
                  to: "/season",
                  search: {
                    edition: game.data.game.summary.edition_id ?? undefined,
                    family: "shots",
                  },
                })
              }
              className="rounded-control border border-accent/50 bg-accent/10 px-2.5 py-1 text-[11px] text-text-primary hover:bg-accent/15"
            >
              SeasonLab · Shots / Drives / Picks
            </button>
            <span className="ml-auto text-[9px] text-text-muted">MIT · SkillCorner attribution requested</span>
          </footer>
        </aside>
      </div>
    </div>
  );

  function seekToEvent(event: (typeof visibleEvents)[number]) {
    const linkedFrame = event.source_clock?.linked_frame_idx;
    if (typeof linkedFrame !== "number") return;
    update({
      period: String(event.source_clock?.period ?? selectedPeriod),
      frame: String(linkedFrame),
      event: event.source_event_id,
      player: event.subject_id ?? undefined,
      entity: event.subject_id ?? undefined,
    });
  }
}

function GameHeader({ game }: { game: BasketballSpatialGameView }) {
  const summary = game.game.summary;
  return (
    <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="t-section">
            {summary.teams
              .map((team) => `${team.display_name} ${team.score ?? "—"}`)
              .join(" · ")} · {game.game.edition.edition_label}
          </p>
          <h1 className="t-surface-title mt-0.5">Basketball spatial game</h1>
        </div>
        <span className="mono ml-auto text-[10px] text-text-muted">
          SkillCorner · {summary.provider_game_id ?? summary.contest_id}
        </span>
      </div>
    </header>
  );
}

function ClockReadout({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <div className="min-w-20 rounded-control border border-border-subtle bg-surface-0 px-2 py-1">
      <span className="block text-[9px] text-text-muted">{label}</span>
      <span className="mono text-[14px] text-text-primary">{formatClock(value)}</span>
    </div>
  );
}

function formatClock(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const seconds = Math.max(0, Math.ceil(value));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
