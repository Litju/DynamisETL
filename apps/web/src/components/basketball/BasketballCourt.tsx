import type {
  BasketballEventView,
  BasketballFrameView,
  BasketballSpatialGameView,
} from "@/api/types";

export function BasketballCourt({
  game,
  frame,
  events,
  selectedEventId,
  selectedPlayerId,
  selectedEntity,
  onEvent,
  onPlayer,
  onBall,
}: {
  game: BasketballSpatialGameView;
  frame: BasketballFrameView;
  events: readonly BasketballEventView[];
  selectedEventId: string | null;
  selectedPlayerId: string | null;
  selectedEntity: string | null;
  onEvent: (event: BasketballEventView) => void;
  onPlayer: (subjectId: string | undefined) => void;
  onBall: () => void;
}) {
  const [away, home] = orderedTeams(game.game.summary.teams);
  const homeId = home?.team_id;
  const selectedName = game.players.find((player) => player.subject_id === selectedPlayerId)?.display_name;
  const selectedFrame = frame;
  return (
    <div className="flex h-full w-full min-h-0 flex-col">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-text-muted">
        <div className="flex items-center gap-3">
          <TeamLegend name={home?.display_name ?? "Home"} color="#ec7c4a" />
          <TeamLegend name={away?.display_name ?? "Away"} color="#5491cb" />
          <TeamLegend name="Ball" color="#ffd166" />
          <TeamLegend name="Events · ±2s" color="#e69fff" />
        </div>
        <span className="mono" data-testid="basketball-clock">
          {selectedEntity === "ball" ? "Selected · Ball" : selectedName ? `Selected · ${selectedName}` : "All players"}
        </span>
      </div>
      <svg
        viewBox="-52 -30 104 60"
        role="img"
        aria-label="Basketball court with source player, ball and event positions"
        className="min-h-0 w-full flex-1 rounded-control border border-border-subtle bg-[#173a37]"
        data-testid="basketball-court"
        data-frame-idx={selectedFrame.frame_idx}
        data-frame-time-ns={selectedFrame.canonical_time_ns}
        data-period={selectedFrame.period_number}
      >
        <g transform="scale(1,-1)" fill="none" stroke="#e9eee8" strokeOpacity="0.8" strokeWidth="0.22">
          <rect x={-47} y={-25} width={94} height={50} rx={0.4} />
          <line x1={0} y1={-25} x2={0} y2={25} />
          <circle cx={0} cy={0} r={6} />
          <rect x={-47} y={-7.5} width={15} height={15} />
          <rect x={32} y={-7.5} width={15} height={15} />
          <path d="M -32 -7.5 A 7.5 7.5 0 0 0 -32 7.5" />
          <path d="M 32 -7.5 A 7.5 7.5 0 0 1 32 7.5" />
          <circle cx={-41.75} cy={0} r={0.75} />
          <circle cx={41.75} cy={0} r={0.75} />
          <path d="M -47 -22 A 24 24 0 0 1 -23 2" />
          <path d="M -47 22 A 24 24 0 0 0 -23 -2" />
          <path d="M 47 -22 A 24 24 0 0 0 23 2" />
          <path d="M 47 22 A 24 24 0 0 1 23 -2" />
        </g>
        <g transform="scale(1,-1)">
          {events.map((event) => {
            const location = event.location;
            if (
              !location ||
              typeof location.x !== "number" ||
              typeof location.y !== "number"
            ) {
              return null;
            }
            const selected = event.source_event_id === selectedEventId;
            return (
              <circle
                key={`event-${event.sequence_index}`}
                cx={location.x}
                cy={location.y}
                r={selected ? 1.25 : 0.8}
                fill={selected ? "#ffffff" : "#e69fff"}
                fillOpacity={selected ? 0.95 : 0.65}
                stroke={selected ? "#e76f51" : "#ffffff"}
                strokeWidth={selected ? 0.4 : 0.2}
                onClick={() => onEvent(event)}
                onKeyDown={(keyEvent) => {
                  if (keyEvent.key === "Enter" || keyEvent.key === " ") onEvent(event);
                }}
                tabIndex={0}
                role="button"
                aria-label={`${event.provider_event_type} at frame ${event.source_clock?.linked_frame_idx ?? "unlinked"}`}
                className="cursor-pointer"
              >
                <title>{event.provider_event_type}</title>
              </circle>
            );
          })}
          {selectedFrame.players.map((player) => {
            const isSelected =
              selectedEntity === player.subject_id || selectedPlayerId === player.subject_id;
            const isHome = player.team_id === homeId;
            return (
              <circle
                key={player.provider_player_id}
                cx={player.x}
                cy={player.y}
                r={isSelected ? 1.05 : 0.74}
                fill={isHome ? "#ec7c4a" : "#5491cb"}
                stroke={isSelected ? "#ffffff" : "#0d1f1e"}
                strokeWidth={isSelected ? 0.42 : 0.2}
                opacity={player.is_detected === false ? 0.56 : 1}
                onClick={() => onPlayer(isSelected ? undefined : player.subject_id)}
                onKeyDown={(keyEvent) => {
                  if (keyEvent.key === "Enter" || keyEvent.key === " ") {
                    onPlayer(isSelected ? undefined : player.subject_id);
                  }
                }}
                tabIndex={0}
                role="button"
                aria-pressed={isSelected}
                aria-label={`Select ${player.display_name}, jersey ${player.jersey ?? "unknown"}`}
                className="cursor-pointer"
              >
                <title>{`#${player.jersey ?? "—"} ${player.display_name}`}</title>
              </circle>
            );
          })}
          {selectedFrame.ball ? (
            <circle
              cx={selectedFrame.ball.x}
              cy={selectedFrame.ball.y}
              r={selectedEntity === "ball" ? 0.85 : 0.62}
              fill="#ffd166"
              stroke={selectedEntity === "ball" ? "#e76f51" : "#392818"}
              strokeWidth={selectedEntity === "ball" ? 0.45 : 0.18}
              data-testid="basketball-ball"
              onClick={onBall}
              onKeyDown={(keyEvent) => {
                if (keyEvent.key === "Enter" || keyEvent.key === " ") onBall();
              }}
              tabIndex={0}
              role="button"
              aria-label={selectedEntity === "ball" ? "Deselect ball" : "Select ball"}
              aria-pressed={selectedEntity === "ball"}
              className="cursor-pointer"
            >
              <title>Ball</title>
            </circle>
          ) : null}
        </g>
        {selectedFrame.players.map((player) => (
          <text
            key={`jersey-${player.provider_player_id}`}
            x={player.x}
            y={-player.y + 0.32}
            textAnchor="middle"
            fontSize="1.3"
            fill="#ffffff"
            pointerEvents="none"
          >
            {player.jersey ?? ""}
          </text>
        ))}
      </svg>
      {selectedFrame.is_dead_time ? (
        <p className="mt-2 text-center text-[10px] text-text-muted" data-testid="dead-time-frame">
          Dead time · source clocks retained · no positions supplied
        </p>
      ) : null}
    </div>
  );
}

function TeamLegend({ name, color }: { name: string; color: string }) {
  return (
    <span className="flex max-w-52 items-center gap-1.5 truncate">
      <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <span className="truncate">{name}</span>
    </span>
  );
}

function orderedTeams(teams: readonly { side: string; team_id: string; display_name: string }[]) {
  return [
    teams.find((team) => team.side === "away"),
    teams.find((team) => team.side === "home"),
  ] as const;
}
