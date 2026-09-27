import { useVirtualizer } from "@tanstack/react-virtual";
import { Search } from "lucide-react";
import { useMemo, useRef, type KeyboardEvent } from "react";

import type { SeasonFamilyView, SeasonRowView } from "@/api/types";
import { cn } from "@/lib/cn";
import { shortTeamName } from "@/lib/season-model";

/** Short lists render directly; long ones are virtualized. */
const VIRTUALIZE_ABOVE = 60;

interface PlayerEntry {
  readonly subjectId: string;
  readonly name: string;
  readonly teamName: string;
  readonly rows: readonly SeasonRowView[];
  readonly matches: number;
  readonly primary: SeasonRowView;
}

function entries(rows: readonly SeasonRowView[], teamId: string | null, query: string): PlayerEntry[] {
  const needle = query.trim().toLowerCase();
  const bySubject = new Map<string, SeasonRowView[]>();
  for (const row of rows) {
    if (teamId && row.team_id !== teamId) continue;
    const list = bySubject.get(row.subject_id) ?? [];
    list.push(row);
    bySubject.set(row.subject_id, list);
  }
  const output: PlayerEntry[] = [];
  for (const [subjectId, list] of bySubject) {
    const primary = [...list].sort((a, b) => (b.matches ?? 0) - (a.matches ?? 0))[0]!;
    const haystack = `${primary.player_name} ${primary.team_name} ${list.map((row) => row.position_group).join(" ")}`.toLowerCase();
    if (needle && !haystack.includes(needle)) continue;
    output.push({
      subjectId,
      name: primary.player_name,
      teamName: primary.team_name,
      rows: list,
      matches: list.reduce((sum, row) => sum + (row.matches ?? 0), 0),
      primary,
    });
  }
  return output.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Team → player navigator for one edition/family. Identity-only rows (no metric
 * values) are loaded once per family; the list is virtualized and keyboard
 * navigable. Selecting a player commits to the URL; the team facet filters the
 * list without mutating the selected player.
 */
export function SeasonNavigator({
  familyView,
  rows,
  pending,
  teamId,
  playerId,
  query,
  onTeam,
  onQuery,
  onPlayer,
}: {
  familyView: SeasonFamilyView;
  rows: readonly SeasonRowView[] | null;
  pending: boolean;
  teamId: string | null;
  playerId: string | null;
  query: string;
  onTeam: (teamId: string | null) => void;
  onQuery: (query: string) => void;
  onPlayer: (row: SeasonRowView) => void;
}) {
  const list = useMemo(() => entries(rows ?? [], teamId, query), [query, rows, teamId]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    count: list.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 44,
    overscan: 8,
  });

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const buttons = [...(scrollRef.current?.querySelectorAll<HTMLButtonElement>("[data-player-row]") ?? [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = buttons[Math.max(0, Math.min(buttons.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
    next?.focus();
  };

  return (
    <aside className="season-navigator flex min-h-0 flex-col border-r border-border-subtle bg-surface-1" aria-label="Team and player navigator">
      <div className="border-b border-border-subtle px-3 pb-3 pt-3">
        <label className="t-section" htmlFor="season-team">Team</label>
        <select
          id="season-team"
          value={teamId ?? ""}
          onChange={(event) => onTeam(event.target.value || null)}
          className="mt-1.5 h-7 w-full rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px] text-text-secondary outline-none focus:border-accent"
        >
          <option value="">All teams · {familyView.teams.length}</option>
          {familyView.teams.map((team) => (
            <option key={team.team_id} value={team.team_id}>
              {shortTeamName(team.display_name)}
            </option>
          ))}
        </select>
        <div className="relative mt-2">
          <Search size={12} aria-hidden="true" className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="search"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Search players"
            aria-label="Search players"
            className="h-7 w-full rounded-control border border-border-subtle bg-surface-0 pl-7 pr-2 text-[12px] text-text-primary outline-none placeholder:text-text-muted focus:border-accent"
          />
        </div>
      </div>
      <div className="flex items-baseline justify-between px-3 pb-1 pt-2">
        <span className="t-section">Players</span>
        <span className="mono text-[10px] text-text-muted">{pending ? "…" : list.length}</span>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-2" onKeyDown={onKeyDown}>
        {pending ? (
          <div className="flex flex-col gap-1 px-1.5" role="status" aria-label="Loading players">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="h-9 animate-pulse rounded-control bg-surface-2" />
            ))}
          </div>
        ) : list.length === 0 ? (
          <p className="px-2 py-4 text-[12px] text-text-muted">No player matches this team and search.</p>
        ) : list.length <= VIRTUALIZE_ABOVE ? (
          <ul role="list">
            {list.map((entry) => (
              <li key={entry.subjectId} className="h-11">
                <PlayerButton entry={entry} active={entry.subjectId === playerId} showTeam={!teamId} onPlayer={onPlayer} />
              </li>
            ))}
          </ul>
        ) : (
          <ul role="list" className="relative" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((item) => {
              const entry = list[item.index]!;
              return (
                <li key={entry.subjectId} className="absolute inset-x-0" style={{ transform: `translateY(${item.start}px)`, height: item.size }}>
                  <PlayerButton entry={entry} active={entry.subjectId === playerId} showTeam={!teamId} onPlayer={onPlayer} />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

function PlayerButton({
  entry,
  active,
  showTeam,
  onPlayer,
}: {
  entry: PlayerEntry;
  active: boolean;
  showTeam: boolean;
  onPlayer: (row: SeasonRowView) => void;
}) {
  return (
    <button
      type="button"
      data-player-row
      aria-current={active ? "true" : undefined}
      onClick={() => onPlayer(entry.primary)}
      className={cn(
        "group relative flex h-10 w-full items-center gap-2 rounded-control px-2 text-left transition-colors duration-quick",
        active ? "bg-surface-3" : "hover:bg-surface-2",
      )}
    >
      {active ? <span aria-hidden="true" className="absolute left-0 top-2 h-6 w-0.5 rounded-r-full bg-accent" /> : null}
      <span className="min-w-0 flex-1">
        <span className={cn("block truncate text-[12px]", active ? "text-text-primary" : "text-text-secondary")}>
          {entry.name}
        </span>
        <span className="block truncate text-[10px] text-text-muted">
          {showTeam ? `${shortTeamName(entry.teamName)} · ` : ""}
          {entry.rows.map((row) => row.position_group).join(" / ")}
        </span>
      </span>
      <span className="mono shrink-0 text-[10px] text-text-muted" title="Included matches across this player's rows">
        {entry.matches}
      </span>
    </button>
  );
}
