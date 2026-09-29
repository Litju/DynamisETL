/**
 * Semantic catalog model for the Research, Data and entity-context screens.
 *
 * Pure projections over the metadata-only RES-125 read model
 * (`/api/catalog/read-model`), the sports match summaries and the dataset
 * summaries. Nothing here reads dense data. Identity is always the served
 * canonical id — display names are never used to join entities.
 */

import type {
  CatalogResourceView,
  DatasetSummary,
  SportsCatalogMatchView,
} from "@/api/types";
import {
  courtWorldTarget,
  editionTarget,
  gameWorldTarget,
  matchWorldTarget,
  performanceWorldTarget,
  seasonWorldTarget,
  studyTarget,
  teamTarget,
  type LinkTarget,
  type WorldId,
} from "@/lib/worlds";

// -- Readiness --------------------------------------------------------------

/** Server-side stage on the Dynamis data plane (upstream is separate). */
export type ServerStage = "none" | "registered" | "materialized" | "ready";

export interface Readiness {
  /** Exists at the provider. */
  readonly upstream: boolean;
  /** Furthest stage reached on the Dynamis data plane. */
  readonly server: ServerStage;
  /** Next deterministic preparation stage the server declares, if any. */
  readonly preparation: string | null;
}

export function readinessOf(resource: CatalogResourceView): Readiness {
  const { stages } = resource;
  const server: ServerStage = stages.ready === "ready"
    ? "ready"
    : stages.materialized === "materialized"
      ? "materialized"
      : stages.registered === "registered"
        ? "registered"
        : "none";
  const preparation = resource.preparation_eligible && server !== "ready"
    ? (resource.preparation_actions ?? [])[0] ?? null
    : null;
  return { upstream: stages.upstream === "available", server, preparation };
}

export const SERVER_STAGE_LABEL: Record<ServerStage, string> = {
  none: "Not materialized",
  registered: "Registered",
  materialized: "Materialized",
  ready: "Ready",
};

// -- Worlds per resource --------------------------------------------------

export type Workbench = "MatchLab" | "Court" | "GameLab" | "SeasonLab" | "PerformanceLab";

export interface WorldLink {
  readonly world: WorldId;
  readonly workbench: Workbench;
  readonly label: string;
  readonly ready: boolean;
  /** Human-readable missing evidence when not ready. */
  readonly missing: readonly string[];
  readonly target: LinkTarget | null;
}

const WORKBENCH_WORLD: Record<Workbench, WorldId> = {
  MatchLab: "match",
  Court: "match",
  GameLab: "game",
  SeasonLab: "season",
  PerformanceLab: "performance",
};

const WORKBENCH_LABEL: Record<Workbench, string> = {
  MatchLab: "Open Match World",
  Court: "Open court",
  GameLab: "Open Game World",
  SeasonLab: "Open Season World",
  PerformanceLab: "Open Performance World",
};

function missingText(route: { missing_capabilities?: string[][]; missing_grains?: string[][] }): string[] {
  const capabilities = (route.missing_capabilities ?? []).map((alternatives) => alternatives.join(" or "));
  const grains = (route.missing_grains ?? []).map((alternatives) => alternatives.join(" or "));
  return [...capabilities, ...grains];
}

/**
 * The Worlds a resource can enter, from the served capability routes.
 *
 * A route is linkable only when the server says it is ready *and* the
 * resource carries the identity the World's URL contract needs. Basketball
 * tracking opens the court (Match World's basketball workbench) and never
 * MatchLab, which is football-only.
 */
export function resourceWorlds(resource: CatalogResourceView): WorldLink[] {
  const links: WorldLink[] = [];
  const datasetId = resource.dataset_ids?.[0] ?? null;
  const basketball = resource.sport_id === "basketball";
  for (const route of resource.routes ?? []) {
    const product = route.product as Workbench;
    let target: LinkTarget | null = null;
    let workbench: Workbench = product;
    if (product === "MatchLab") {
      if (basketball) {
        workbench = "Court";
        target = resource.basketball_spatial_ready && resource.contest_id ? courtWorldTarget(resource.contest_id) : null;
      } else if (resource.session_id && datasetId) {
        target = matchWorldTarget(datasetId, resource.session_id);
      }
    } else if (product === "GameLab" && resource.edition_id) {
      target = gameWorldTarget(resource.edition_id, resource.contest_id);
    } else if (product === "SeasonLab" && resource.edition_id) {
      target = seasonWorldTarget(resource.edition_id);
    } else if (product === "PerformanceLab" && resource.session_id && datasetId) {
      target = performanceWorldTarget(datasetId, resource.session_id);
    }
    const ready = product === "MatchLab" && basketball
      ? Boolean(resource.basketball_spatial_ready)
      : route.ready;
    links.push({
      world: WORKBENCH_WORLD[workbench],
      workbench,
      label: WORKBENCH_LABEL[workbench],
      ready: ready && target !== null,
      missing: ready ? [] : missingText(route),
      target: ready ? target : null,
    });
  }
  return links;
}

export function primaryWorld(resource: CatalogResourceView): WorldLink | null {
  const worlds = resourceWorlds(resource);
  return worlds.find((link) => link.ready) ?? null;
}

// -- Labels ------------------------------------------------------------------

/** Contest title with the served score, e.g. "Auckland FC 2–1 Macarthur FC". */
export function contestTitle(resource: Pick<CatalogResourceView, "label" | "teams">): string {
  const teams = resource.teams ?? [];
  const home = teams.find((team) => team.side === "home");
  const away = teams.find((team) => team.side === "away");
  if (!home || !away) return resource.label;
  if (home.score !== null && home.score !== undefined && away.score !== null && away.score !== undefined) {
    return `${home.display_name} ${home.score}–${away.score} ${away.display_name}`;
  }
  return `${home.display_name} vs ${away.display_name}`;
}

export function editionTitle(resource: Pick<CatalogResourceView, "competition_name" | "edition_label" | "label">): string {
  return [resource.competition_name, resource.edition_label ?? resource.label].filter(Boolean).join(" ");
}

/** Readable short dataset name: the provider title before any em-dash detail. */
export function shortDatasetName(name: string): string {
  const head = name.split(" — ")[0]?.trim() || name;
  return head.replace(/\s*\([^)]*\)\s*$/u, "").trim() || head;
}

const SPORT_ORDER = ["football", "basketball", "ice_hockey"];

export function sportRank(sportId: string): number {
  const index = SPORT_ORDER.indexOf(sportId);
  return index === -1 ? SPORT_ORDER.length : index;
}

// -- Sports hierarchy -----------------------------------------------------

export interface EditionNode {
  readonly editionId: string;
  readonly label: string;
  readonly competitionId: string;
  readonly competitionName: string;
  readonly sportId: string;
  readonly sportName: string;
  readonly resource: CatalogResourceView | null;
  readonly contests: readonly CatalogResourceView[];
  readonly readyContests: number;
  readonly upstreamContests: number;
  readonly worlds: readonly WorldLink[];
  readonly ready: boolean;
}

export interface CompetitionNode {
  readonly competitionId: string;
  readonly name: string;
  readonly sportId: string;
  readonly editions: readonly EditionNode[];
  readonly readyEditions: number;
}

export interface SportNode {
  readonly sportId: string;
  readonly name: string;
  readonly competitions: readonly CompetitionNode[];
  readonly editionCount: number;
  readonly readyEditions: number;
  readonly contestCount: number;
  readonly readyContests: number;
}

export function buildSportsTree(resources: readonly CatalogResourceView[]): SportNode[] {
  const editions = new Map<string, {
    resource: CatalogResourceView | null;
    contests: CatalogResourceView[];
    base: CatalogResourceView;
  }>();
  for (const resource of resources) {
    if (!resource.sport_id || !resource.edition_id) continue;
    if (resource.resource_kind !== "competition_edition" && resource.resource_kind !== "contest") continue;
    const entry = editions.get(resource.edition_id) ?? { resource: null, contests: [], base: resource };
    if (resource.resource_kind === "competition_edition") entry.resource = resource;
    else entry.contests.push(resource);
    editions.set(resource.edition_id, entry);
  }

  const competitions = new Map<string, { node: Omit<CompetitionNode, "editions" | "readyEditions">; editions: EditionNode[] }>();
  for (const [editionId, entry] of editions) {
    const base = entry.resource ?? entry.base;
    const readyContests = entry.contests.filter((contest) => readinessOf(contest).server === "ready").length;
    const worlds = entry.resource ? resourceWorlds(entry.resource) : [];
    const node: EditionNode = {
      editionId,
      label: base.edition_label ?? entry.resource?.label ?? editionId,
      competitionId: base.competition_id ?? editionId,
      competitionName: base.competition_name ?? "Competition",
      sportId: base.sport_id!,
      sportName: base.sport_name ?? base.sport_id!,
      resource: entry.resource,
      contests: entry.contests,
      readyContests,
      upstreamContests: entry.contests.length - readyContests,
      worlds,
      ready: worlds.some((link) => link.ready) || readyContests > 0,
    };
    const key = node.competitionId;
    const competition = competitions.get(key) ?? {
      node: { competitionId: key, name: node.competitionName, sportId: node.sportId },
      editions: [],
    };
    competition.editions.push(node);
    competitions.set(key, competition);
  }

  const sports = new Map<string, { name: string; competitions: CompetitionNode[] }>();
  for (const { node, editions: list } of competitions.values()) {
    const sorted = [...list].sort((a, b) => b.label.localeCompare(a.label));
    const competition: CompetitionNode = {
      ...node,
      editions: sorted,
      readyEditions: sorted.filter((edition) => edition.ready).length,
    };
    const sport = sports.get(node.sportId) ?? { name: sorted[0]?.sportName ?? node.sportId, competitions: [] };
    sport.competitions.push(competition);
    sports.set(node.sportId, sport);
  }

  return [...sports.entries()]
    .map(([sportId, sport]): SportNode => {
      const competitionsSorted = [...sport.competitions].sort(
        (a, b) => b.readyEditions - a.readyEditions || a.name.localeCompare(b.name),
      );
      const allEditions = competitionsSorted.flatMap((competition) => competition.editions);
      return {
        sportId,
        name: sport.name,
        competitions: competitionsSorted,
        editionCount: allEditions.length,
        readyEditions: allEditions.filter((edition) => edition.ready).length,
        contestCount: allEditions.reduce((sum, edition) => sum + edition.contests.length, 0),
        readyContests: allEditions.reduce((sum, edition) => sum + edition.readyContests, 0),
      };
    })
    .sort((a, b) => sportRank(a.sportId) - sportRank(b.sportId) || a.name.localeCompare(b.name));
}

export function findEdition(tree: readonly SportNode[], editionId: string): EditionNode | null {
  for (const sport of tree) {
    for (const competition of sport.competitions) {
      const edition = competition.editions.find((candidate) => candidate.editionId === editionId);
      if (edition) return edition;
    }
  }
  return null;
}

export interface TeamSummary {
  readonly teamId: string;
  readonly name: string;
  readonly contests: readonly CatalogResourceView[];
  readonly readyContests: number;
}

/** Teams that appear in an edition's registered contests (authoritative membership). */
export function teamsForContests(contests: readonly CatalogResourceView[]): TeamSummary[] {
  const teams = new Map<string, { name: string; contests: CatalogResourceView[] }>();
  for (const contest of contests) {
    for (const team of contest.teams ?? []) {
      const entry = teams.get(team.team_id) ?? { name: team.display_name, contests: [] };
      entry.contests.push(contest);
      teams.set(team.team_id, entry);
    }
  }
  return [...teams.entries()]
    .map(([teamId, entry]) => ({
      teamId,
      name: entry.name,
      contests: entry.contests,
      readyContests: entry.contests.filter((contest) => readinessOf(contest).server === "ready").length,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function contestDate(
  contest: Pick<CatalogResourceView, "contest_id">,
  matches: ReadonlyMap<string, SportsCatalogMatchView>,
): string | null {
  const match = contest.contest_id ? matches.get(contest.contest_id) : undefined;
  return match?.actual_start_at ?? match?.scheduled_start_at ?? null;
}

// -- Human performance ----------------------------------------------------

export const HUMAN_MODALITIES = [
  { id: "force", label: "Force", detail: "Ground reaction force plates" },
  { id: "imu", label: "IMU", detail: "Inertial sensors" },
  { id: "gnss", label: "GNSS", detail: "Satellite positioning" },
  { id: "lpt", label: "LPT", detail: "Linear position transducers" },
] as const;
export type HumanModality = (typeof HUMAN_MODALITIES)[number]["id"];

export interface StudyNode {
  readonly datasetId: string;
  readonly name: string;
  readonly shortName: string;
  readonly provider: string;
  readonly domain: string;
  readonly modalities: readonly string[];
  readonly ingestedModalities: readonly string[];
  readonly license: string | null;
  readonly noncommercial: boolean;
  readonly sessionCount: number;
  readonly readySessions: number;
  readonly subjectCount: number;
  readonly trialCount: number;
  readonly ready: boolean;
  readonly sessions: readonly CatalogResourceView[];
}

const SIGNAL_SET = new Set<string>(HUMAN_MODALITIES.map((modality) => modality.id));

export function buildStudies(
  datasets: readonly DatasetSummary[],
  resources: readonly CatalogResourceView[],
): StudyNode[] {
  const sessionsByDataset = new Map<string, CatalogResourceView[]>();
  for (const resource of resources) {
    if (resource.resource_kind !== "performance_session") continue;
    const datasetId = resource.dataset_ids?.[0];
    if (!datasetId) continue;
    const list = sessionsByDataset.get(datasetId) ?? [];
    list.push(resource);
    sessionsByDataset.set(datasetId, list);
  }
  return datasets
    .filter((dataset) => dataset.modalities.some((modality) => SIGNAL_SET.has(modality)))
    .map((dataset): StudyNode => {
      const sessions = sessionsByDataset.get(dataset.dataset_id) ?? [];
      const readySessions = sessions.filter((session) => readinessOf(session).server === "ready").length;
      return {
        datasetId: dataset.dataset_id,
        name: dataset.name,
        shortName: shortDatasetName(dataset.name),
        provider: dataset.provider,
        domain: dataset.domain,
        modalities: dataset.modalities.filter((modality) => SIGNAL_SET.has(modality)),
        ingestedModalities: dataset.ingested_modalities,
        license: dataset.license.identifier ?? null,
        noncommercial: dataset.license.noncommercial_only,
        sessionCount: dataset.session_count,
        readySessions,
        subjectCount: dataset.subject_count,
        trialCount: dataset.trial_count,
        ready: readySessions > 0,
        sessions,
      };
    })
    .sort((a, b) => Number(b.ready) - Number(a.ready) || a.shortName.localeCompare(b.shortName));
}

export function studiesForModality(studies: readonly StudyNode[], modality: string): StudyNode[] {
  return studies.filter((study) => study.modalities.includes(modality));
}

// -- Search -------------------------------------------------------------------

export type CatalogHitKind = "edition" | "contest" | "team" | "study" | "session";

export interface CatalogHit {
  readonly key: string;
  readonly kind: CatalogHitKind;
  readonly title: string;
  readonly subtitle: string;
  readonly world: WorldId | null;
  readonly ready: boolean;
  readonly target: LinkTarget;
  readonly score: number;
}

function scoreText(haystack: string, needles: readonly string[]): number {
  let score = 0;
  for (const needle of needles) {
    const index = haystack.indexOf(needle);
    if (index === -1) return 0;
    score += index === 0 ? 3 : haystack[index - 1] === " " ? 2 : 1;
  }
  return score;
}

/**
 * Metadata-only catalog search across editions, contests, teams and studies.
 * Ready items rank above upstream-only ones at equal textual relevance.
 */
export function searchCatalog(
  resources: readonly CatalogResourceView[],
  studies: readonly StudyNode[],
  query: string,
  limit = 12,
): CatalogHit[] {
  const needles = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (needles.length === 0) return [];
  const hits: CatalogHit[] = [];
  const teamsSeen = new Set<string>();
  for (const resource of resources) {
    if (resource.resource_kind === "performance_session") continue;
    const ready = readinessOf(resource).server === "ready";
    const context = [resource.sport_name, resource.competition_name, resource.edition_label].filter(Boolean).join(" · ");
    if (resource.resource_kind === "competition_edition" && resource.edition_id) {
      const title = editionTitle(resource);
      const score = scoreText(`${title} ${resource.sport_name ?? ""}`.toLocaleLowerCase(), needles);
      if (score > 0) {
        hits.push({
          key: `edition:${resource.edition_id}`,
          kind: "edition",
          title,
          subtitle: `${resource.sport_name ?? ""} · competition edition`,
          world: null,
          ready,
          target: editionTarget(resource.edition_id),
          score: score + (ready ? 1 : 0),
        });
      }
    }
    if (resource.resource_kind === "contest") {
      const title = contestTitle(resource);
      const score = scoreText(`${title} ${context} ${(resource.external_ids ?? []).join(" ")}`.toLocaleLowerCase(), needles);
      if (score > 0) {
        const world = primaryWorld(resource);
        hits.push({
          key: `contest:${resource.resource_id}`,
          kind: "contest",
          title,
          subtitle: context,
          world: world?.world ?? null,
          ready: world !== null,
          target: world?.target ?? (resource.edition_id ? editionTarget(resource.edition_id) : { to: "/data" }),
          score: score + (world ? 2 : 0),
        });
      }
      for (const team of resource.teams ?? []) {
        if (teamsSeen.has(team.team_id)) continue;
        const teamScore = scoreText(team.display_name.toLocaleLowerCase(), needles);
        if (teamScore > 0) {
          teamsSeen.add(team.team_id);
          hits.push({
            key: `team:${team.team_id}`,
            kind: "team",
            title: team.display_name,
            subtitle: context,
            world: null,
            ready,
            target: teamTarget(team.team_id, resource.edition_id),
            score: teamScore + 1,
          });
        }
      }
    }
  }
  for (const study of studies) {
    const score = scoreText(`${study.name} ${study.provider} ${study.modalities.join(" ")}`.toLocaleLowerCase(), needles);
    if (score > 0) {
      hits.push({
        key: `study:${study.datasetId}`,
        kind: "study",
        title: study.shortName,
        subtitle: `Human performance · ${study.modalities.map((modality) => modality.toUpperCase()).join(" · ")}`,
        world: "performance",
        ready: study.ready,
        target: studyTarget(study.datasetId),
        score: score + (study.ready ? 1 : 0),
      });
    }
  }
  return hits.sort((a, b) => b.score - a.score || a.title.localeCompare(b.title)).slice(0, limit);
}

// -- Readiness summary ----------------------------------------------------

export interface CatalogSummary {
  readonly contests: number;
  readonly readyContests: number;
  readonly upstreamOnlyContests: number;
  readonly editions: number;
  readonly readyEditions: number;
  readonly sessions: number;
  readonly readySessions: number;
  readonly preparable: number;
}

export function summarizeCatalog(resources: readonly CatalogResourceView[]): CatalogSummary {
  let contests = 0;
  let readyContests = 0;
  let upstreamOnlyContests = 0;
  let editions = 0;
  let readyEditions = 0;
  let sessions = 0;
  let readySessions = 0;
  let preparable = 0;
  for (const resource of resources) {
    const readiness = readinessOf(resource);
    if (readiness.preparation) preparable += 1;
    if (resource.resource_kind === "contest") {
      contests += 1;
      if (readiness.server === "ready") readyContests += 1;
      else if (readiness.server === "none" || readiness.server === "registered") upstreamOnlyContests += 1;
    } else if (resource.resource_kind === "competition_edition") {
      editions += 1;
      if (readiness.server === "ready") readyEditions += 1;
    } else if (resource.resource_kind === "performance_session") {
      sessions += 1;
      if (readiness.server === "ready") readySessions += 1;
    }
  }
  return { contests, readyContests, upstreamOnlyContests, editions, readyEditions, sessions, readySessions, preparable };
}
