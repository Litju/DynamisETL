/**
 * Data Worlds — the V4 product model.
 *
 * A World is an analytical environment selected by capability and data grain,
 * never by provider. A catalog resource routes into the pertinent World through
 * the served capability routes (RES-125 `routes`), and each World owns one
 * durable URL context schema (see `lib/search.ts`).
 *
 *   Match World        → continuous spatial contest (FRAME_SERIES): MatchLab,
 *                        or the basketball court for basketball tracking;
 *   Game World         → play-by-play / box score (PLAY_BY_PLAY);
 *   Season World       → player/team season aggregates (PLAYER_SEASON);
 *   Performance World  → force / IMU / GNSS / LPT trials (TRIAL_SERIES).
 *
 * This module is pure: it maps locations and resources to Worlds and builds
 * typed link targets. It never fetches.
 */

export const WORLD_IDS = ["match", "game", "season", "performance"] as const;
export type WorldId = (typeof WORLD_IDS)[number];

/** Product sections of the global information architecture. */
export type Section = "research" | "data" | "library" | "world" | "other";

export interface WorldMeta {
  readonly id: WorldId;
  readonly label: string;
  /** The single question the World answers. */
  readonly question: string;
  /** Primary data grain the World is built for. */
  readonly grain: string;
  /** What the first screen leads with. */
  readonly lead: string;
  readonly entry: string;
}

export const WORLDS: Record<WorldId, WorldMeta> = {
  match: {
    id: "match",
    label: "Match World",
    question: "What is happening spatially in this contest, at this moment?",
    grain: "FRAME_SERIES",
    lead: "Spatial and tactical first",
    entry: "/lab",
  },
  game: {
    id: "game",
    label: "Game World",
    question: "How did this game unfold, play by play?",
    grain: "PLAY_BY_PLAY",
    lead: "Game state first",
    entry: "/games",
  },
  season: {
    id: "season",
    label: "Season World",
    question: "Where does this player or team sit across a season?",
    grain: "PLAYER_SEASON",
    lead: "Distribution and profile first",
    entry: "/season",
  },
  performance: {
    id: "performance",
    label: "Performance World",
    question: "What does this trial's signal show?",
    grain: "TRIAL_SERIES",
    lead: "Signal and trial first",
    entry: "/performance",
  },
};

/** A typed, serializable router target (router `to` + params + search). */
export interface LinkTarget {
  readonly to: string;
  readonly params?: Readonly<Record<string, string>>;
  readonly search?: Readonly<Record<string, string>>;
}

/** Render a link target as an href (for recents, copy links, tests). */
export function hrefOf(target: LinkTarget): string {
  let path = target.to;
  for (const [key, value] of Object.entries(target.params ?? {})) {
    path = path.replace(`$${key}`, encodeURIComponent(value));
  }
  const query = new URLSearchParams(
    Object.entries(target.search ?? {}).filter(([, value]) => value !== undefined && value !== ""),
  ).toString();
  return query ? `${path}?${query}` : path;
}

/** Parse a stored href (recent context) back into a typed target. */
export function targetFromHref(href: string): LinkTarget {
  const [path = "/", query = ""] = href.split("?");
  const search = Object.fromEntries(new URLSearchParams(query).entries());
  return Object.keys(search).length ? { to: path, search } : { to: path };
}

export const matchWorldTarget = (
  datasetId: string,
  sessionId: string,
  search: Readonly<Record<string, string>> = {},
): LinkTarget => ({
  to: "/lab/$datasetId/$sessionId",
  params: { datasetId, sessionId },
  search: { view: "matchlab", ...search },
});

export const courtWorldTarget = (contestId: string, search: Readonly<Record<string, string>> = {}): LinkTarget => ({
  to: "/basketball",
  search: { contest: contestId, ...search },
});

export const gameWorldTarget = (editionId: string, gameId?: string | null): LinkTarget => ({
  to: "/games",
  search: gameId ? { edition: editionId, game: gameId } : { edition: editionId },
});

export const seasonWorldTarget = (
  editionId: string,
  search: Readonly<Record<string, string>> = {},
): LinkTarget => ({
  to: "/season",
  search: { edition: editionId, ...search },
});

export const performanceWorldTarget = (
  datasetId: string,
  sessionId: string,
  search: Readonly<Record<string, string>> = {},
): LinkTarget => ({
  to: "/lab/$datasetId/$sessionId",
  params: { datasetId, sessionId },
  search: { view: "signals", ...search },
});

export const studyTarget = (datasetId: string, search: Readonly<Record<string, string>> = {}): LinkTarget => ({
  to: "/performance",
  search: { dataset: datasetId, ...search },
});

export const editionTarget = (editionId: string, tab?: string): LinkTarget => ({
  to: "/data/edition/$editionId",
  params: { editionId },
  ...(tab ? { search: { tab } } : {}),
});

export const teamTarget = (teamId: string, editionId?: string | null): LinkTarget => ({
  to: "/data/team/$teamId",
  params: { teamId },
  ...(editionId ? { search: { edition: editionId } } : {}),
});

export const playerTarget = (subjectId: string, editionId?: string | null): LinkTarget => ({
  to: "/data/player/$subjectId",
  params: { subjectId },
  ...(editionId ? { search: { edition: editionId } } : {}),
});

/** Datasets whose sessions are laboratory trials rather than sports contests. */
export function isPerformanceDomain(domain: string | null | undefined): boolean {
  return domain === "laboratory";
}

export interface LocationWorld {
  readonly section: Section;
  readonly world: WorldId | null;
  /** True on a World's entry/navigator surface rather than its workbench. */
  readonly entry: boolean;
}

/**
 * Resolve the section and World for a location.
 *
 * `/lab/:dataset/:session` is shared by Match and Performance Worlds; the
 * dataset domain decides (laboratory datasets are trials, not contests). When
 * the domain is not yet known the view decides: tactical/spatial views are
 * Match World, signal views are Performance World.
 */
export function worldForLocation(
  pathname: string,
  search: Readonly<Record<string, unknown>> = {},
  datasetDomain?: string | null,
): LocationWorld {
  const parts = pathname.split("/").filter(Boolean);
  const head = parts[0] ?? "";
  if (head === "") return { section: "research", world: null, entry: false };
  if (head === "data" || head === "catalog") return { section: "data", world: null, entry: false };
  if (head === "library" || head === "methods" || head === "runs" || head === "quality") {
    return { section: "library", world: null, entry: false };
  }
  if (head === "games") return { section: "world", world: "game", entry: !search.game };
  if (head === "season") return { section: "world", world: "season", entry: !search.edition };
  if (head === "basketball") return { section: "world", world: "match", entry: !search.contest };
  if (head === "performance" || head === "compare") return { section: "world", world: "performance", entry: head === "performance" };
  if (head === "lab") {
    if (!parts[1] || !parts[2]) return { section: "world", world: "match", entry: true };
    if (datasetDomain !== undefined && datasetDomain !== null) {
      return { section: "world", world: isPerformanceDomain(datasetDomain) ? "performance" : "match", entry: false };
    }
    const view = typeof search.view === "string" ? search.view : "overview";
    const spatial = view === "matchlab" || view === "field" || view === "pose";
    return { section: "world", world: spatial ? "match" : "performance", entry: false };
  }
  return { section: "other", world: null, entry: false };
}
