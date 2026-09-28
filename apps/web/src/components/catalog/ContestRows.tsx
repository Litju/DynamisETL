import { ArrowRight, Database } from "lucide-react";
import { useState } from "react";

import type { CatalogResourceView, GameSummaryView, SportsCatalogMatchView } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { ServerReadiness } from "@/components/common/Readiness";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { PrepareDialog } from "@/components/catalog/PrepareDialog";
import { contestDate, primaryWorld, readinessOf } from "@/lib/catalog-model";
import { cn } from "@/lib/cn";
import { gameWorldTarget } from "@/lib/worlds";

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

const CAPABILITY_LABEL: Record<string, string> = {
  TRACKING: "Tracking",
  POSE: "Pose",
  EVENTS: "Events",
  BALL_TRACKING: "Ball",
  PHASES: "Phases",
  PLAY_BY_PLAY: "Play-by-play",
  BOX_SCORE: "Box score",
};

/** Capability chips: filled = materialized locally, dashed = source only. */
export function CapabilityChips({ resource }: { resource: CatalogResourceView }) {
  const local = new Set(resource.materialized_capabilities ?? []);
  const upstream = resource.upstream_capabilities ?? [];
  const all = [...new Set([...upstream, ...local])].filter((capability) => CAPABILITY_LABEL[capability]);
  return (
    <span className="flex flex-wrap gap-1" aria-label="Capabilities: local and source">
      {all.map((capability) => {
        const isLocal = local.has(capability);
        return (
          <span
            key={capability}
            title={`${CAPABILITY_LABEL[capability]} — ${isLocal ? "materialized locally" : "available at source only"}`}
            className={cn(
              "rounded-[4px] border px-1.5 py-px text-[10.5px]",
              isLocal
                ? "border-[color-mix(in_oklab,var(--d-ready-ready)_45%,transparent)] text-text-secondary"
                : "border-dashed border-border-subtle text-text-faint",
            )}
          >
            {CAPABILITY_LABEL[capability]}
            <span className="sr-only">{isLocal ? " (local)" : " (source only)"}</span>
          </span>
        );
      })}
    </span>
  );
}

function Teams({ resource }: { resource: Pick<CatalogResourceView, "teams" | "label"> }) {
  const home = resource.teams?.find((team) => team.side === "home");
  const away = resource.teams?.find((team) => team.side === "away");
  if (!home || !away) return <span className="truncate text-text-primary">{resource.label}</span>;
  const scored = home.score !== null && home.score !== undefined && away.score !== null && away.score !== undefined;
  return (
    <span className="grid min-w-0 grid-cols-[minmax(0,1fr)_3.25rem_minmax(0,1fr)] items-center gap-2">
      <span className="truncate text-right text-text-primary">{home.display_name}</span>
      <span className="mono text-center text-[12px] text-text-secondary">{scored ? `${home.score}–${away.score}` : "vs"}</span>
      <span className="truncate text-text-primary">{away.display_name}</span>
    </span>
  );
}

/** One contest from the semantic read model with its primary action. */
export function ContestRow({
  contest,
  matches,
  gameEditionId,
}: {
  contest: CatalogResourceView;
  matches: ReadonlyMap<string, SportsCatalogMatchView>;
  /** Edition whose Game World serves this contest's play-by-play, if any. */
  gameEditionId?: string | null;
}) {
  const world = primaryWorld(contest);
  const readiness = readinessOf(contest);
  // The plan dialog stays mounted while open: the row may become ready
  // underneath it, and the reader should see that success in place.
  const [prepareOpen, setPrepareOpen] = useState(false);
  const gameTarget = gameEditionId && contest.contest_id ? gameWorldTarget(gameEditionId, contest.contest_id) : null;
  return (
    <li className="d-row contest-grid px-5 py-2.5 text-[12.5px]">
      <span className="c-date mono text-[11px] text-text-muted">{formatDate(contestDate(contest, matches))}</span>
      <span className="c-teams min-w-0"><Teams resource={contest} /></span>
      <span className="c-caps min-w-0"><CapabilityChips resource={contest} /></span>
      <span className="c-ready"><ServerReadiness stage={readiness.server} upstream={readiness.upstream} compact /></span>
      <span className="c-action flex items-center justify-end gap-1.5">
        {gameTarget ? (
          <AppLink to={gameTarget} transition className="d-btn d-btn-ghost px-1.5" aria-label={`Play-by-play in Game World: ${contest.label}`} title="Play-by-play in Game World">
            <WorldGlyph world="game" size="sm" className="text-text-muted" />
          </AppLink>
        ) : null}
        {world?.target && !prepareOpen ? (
          <AppLink to={world.target} transition className="d-btn group border-selected-border text-text-primary" aria-label={`${world.label}: ${contest.label}`}>
            <WorldGlyph world={world.world} size="sm" className="text-accent" />
            {world.workbench === "Court" ? "Open court" : "Open match"}
          </AppLink>
        ) : readiness.preparation === "acquire" || prepareOpen ? (
          <PrepareDialog
            resource={contest}
            open={prepareOpen}
            onOpenChange={setPrepareOpen}
            trigger={<><Database size={12} aria-hidden="true" /> Prepare locally</>}
          />
        ) : (
          <span className="text-[11px] text-text-faint">{readiness.preparation ? `Awaiting ${readiness.preparation}` : "Not routable"}</span>
        )}
      </span>
    </li>
  );
}

export function ContestListHeader() {
  return (
    <div className="contest-grid border-b border-border-subtle px-5 py-2 text-[10.5px] uppercase tracking-[0.08em] text-text-faint">
      <span className="c-date">Date</span>
      <span className="c-teams text-center">Home · Away</span>
      <span className="c-caps">Capabilities</span>
      <span className="c-ready">Readiness</span>
      <span className="c-action text-right">Action</span>
    </div>
  );
}

/** One play-by-play game summary (Game World grain). */
export function GameRow({ game, editionId, style }: { game: GameSummaryView; editionId: string; style?: React.CSSProperties }) {
  const home = game.teams.find((team) => team.side === "home");
  const away = game.teams.find((team) => team.side === "away");
  return (
    <AppLink
      to={gameWorldTarget(editionId, game.contest_id)}
      transition
      style={style}
      className="d-row group grid grid-cols-[6.5rem_minmax(0,1fr)_7rem_1rem] items-center gap-4 px-5 text-[12.5px]"
    >
      <span className="mono text-[11px] text-text-muted">{formatDate(game.actual_start_at ?? game.scheduled_start_at)}</span>
      <span className="grid min-w-0 grid-cols-[minmax(0,1fr)_3.5rem_minmax(0,1fr)] items-center gap-2">
        <span className="truncate text-right text-text-primary">{away?.display_name ?? "—"}</span>
        <span className="mono text-center text-[12px] text-text-secondary">
          {away?.score !== null && away?.score !== undefined && home?.score !== null && home?.score !== undefined ? `${away.score}–${home.score}` : "@"}
        </span>
        <span className="truncate text-text-primary">{home?.display_name ?? "—"}</span>
      </span>
      <span className="text-[11px] text-text-muted">
        {game.play_by_play_available ? "Play-by-play" : "Summary only"}{game.postseason ? " · post" : ""}
      </span>
      <ArrowRight size={12} aria-hidden="true" className="text-text-faint group-hover:text-accent" />
    </AppLink>
  );
}
