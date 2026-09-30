import { describe, expect, it } from "vitest";

import type { CatalogResourceView, DatasetSummary } from "@/api/types";
import {
  buildSportsTree,
  buildStudies,
  contestTitle,
  primaryWorld,
  readinessOf,
  resourceWorlds,
  searchCatalog,
  summarizeCatalog,
  teamsForContests,
} from "@/lib/catalog-model";
import { hrefOf, targetFromHref, worldForLocation } from "@/lib/worlds";

const READY = { upstream: "available", registered: "registered", materialized: "materialized", ready: "ready" } as const;
const UPSTREAM = { upstream: "available", registered: "registered", materialized: "not_materialized", ready: "not_ready" } as const;

function contest(overrides: Partial<CatalogResourceView> = {}): CatalogResourceView {
  return {
    resource_kind: "contest",
    resource_id: "contest-a",
    label: "Auckland FC 2-1 Macarthur FC",
    dataset_ids: ["skillcorner-opendata"],
    providers: ["SkillCorner / PySport"],
    source_entry_ids: ["src-a"],
    external_ids: ["1996436"],
    sport_id: "football",
    sport_name: "Football",
    competition_id: "comp-aleague",
    competition_name: "A-League",
    edition_id: "edition-aleague",
    edition_label: "2024/2025",
    contest_id: "contest-a",
    teams: [
      { team_id: "team-auckland", display_name: "Auckland FC", side: "home", score: 2 },
      { team_id: "team-macarthur", display_name: "Macarthur FC", side: "away", score: 1 },
    ],
    session_id: "1996436",
    rights_identifiers: ["MIT"],
    noncommercial_only: false,
    local_only: false,
    availability_state: "MATERIALIZED",
    stages: READY,
    upstream_capabilities: ["TRACKING"],
    registered_capabilities: ["TRACKING"],
    materialized_capabilities: ["TRACKING"],
    materialized_grains: ["FRAME_SERIES"],
    routes: [{ product: "MatchLab", ready: true, missing_capabilities: [], missing_grains: [] }],
    basketball_spatial_ready: false,
    preparation_eligible: true,
    preparation_actions: ["validate"],
    ...overrides,
  } as CatalogResourceView;
}

const upstreamContest = contest({
  resource_id: "contest-b",
  contest_id: "contest-b",
  session_id: "1874553",
  label: "Brisbane Roar FC 2-3 Adelaide United",
  teams: [
    { team_id: "team-brisbane", display_name: "Brisbane Roar FC", side: "home", score: 2 },
    { team_id: "team-auckland", display_name: "Auckland FC", side: "away", score: 3 },
  ],
  stages: UPSTREAM,
  materialized_capabilities: [],
  materialized_grains: [],
  routes: [{ product: "MatchLab", ready: false, missing_capabilities: [["TRACKING"]], missing_grains: [["FRAME_SERIES"]] }],
  preparation_actions: ["acquire"],
});

const seasonEdition = contest({
  resource_kind: "competition_edition",
  resource_id: "edition-aleague",
  label: "2024/2025",
  contest_id: null,
  session_id: null,
  teams: [],
  routes: [
    { product: "SeasonLab", ready: true, missing_capabilities: [], missing_grains: [] },
    { product: "GameLab", ready: false, missing_capabilities: [["PLAY_BY_PLAY", "EVENTS"]], missing_grains: [] },
  ],
});

const courtContest = contest({
  resource_id: "contest-court",
  contest_id: "contest-court",
  sport_id: "basketball",
  sport_name: "Basketball",
  competition_id: "comp-acb",
  competition_name: "Liga ACB",
  edition_id: "edition-acb",
  edition_label: "2025-2026",
  basketball_spatial_ready: true,
});

describe("catalog readiness", () => {
  it("keeps upstream, server and preparation as separate facts", () => {
    expect(readinessOf(contest())).toEqual({ upstream: true, server: "ready", preparation: null });
    expect(readinessOf(upstreamContest)).toEqual({ upstream: true, server: "registered", preparation: "acquire" });
  });

  it("summarizes ready and upstream-only contests without conflating them", () => {
    const summary = summarizeCatalog([contest(), upstreamContest, seasonEdition]);
    expect(summary.contests).toBe(2);
    expect(summary.readyContests).toBe(1);
    expect(summary.upstreamOnlyContests).toBe(1);
    expect(summary.readyEditions).toBe(1);
    expect(summary.preparable).toBe(1);
  });
});

describe("World routing", () => {
  it("routes a ready football contest into Match World with its session identity", () => {
    const world = primaryWorld(contest());
    expect(world?.world).toBe("match");
    expect(world?.workbench).toBe("MatchLab");
    expect(world?.target && hrefOf(world.target)).toBe("/lab/skillcorner-opendata/1996436?view=matchlab");
  });

  it("never links an upstream-only contest and reports what is missing", () => {
    const [link] = resourceWorlds(upstreamContest);
    expect(link?.ready).toBe(false);
    expect(link?.target).toBeNull();
    expect(link?.missing).toEqual(["TRACKING", "FRAME_SERIES"]);
  });

  it("keeps a manifest-incomplete registered contest non-openable", () => {
    const incomplete = contest({
      availability_state: "REGISTERED",
      stages: { ...READY, materialized: "not_materialized", ready: "not_ready" },
      routes: [
        {
          product: "MatchLab",
          ready: false,
          missing_capabilities: [],
          missing_grains: [],
        },
      ],
    });
    const [link] = resourceWorlds(incomplete);
    expect(link?.ready).toBe(false);
    expect(link?.target).toBeNull();
  });

  it("opens basketball tracking on the court, not in football MatchLab", () => {
    const world = primaryWorld(courtContest);
    expect(world?.workbench).toBe("Court");
    expect(world?.world).toBe("match");
    expect(world?.target && hrefOf(world.target)).toBe("/basketball?contest=contest-court");
  });

  it("routes an edition only to the Worlds its grain supports", () => {
    const links = resourceWorlds(seasonEdition);
    expect(links.filter((link) => link.ready).map((link) => link.world)).toEqual(["season"]);
  });

  it("resolves sections and Worlds from locations", () => {
    expect(worldForLocation("/")).toEqual({ section: "research", world: null, entry: false });
    expect(worldForLocation("/data/edition/x").section).toBe("data");
    expect(worldForLocation("/methods").section).toBe("library");
    expect(worldForLocation("/games", { edition: "e" })).toEqual({ section: "world", world: "game", entry: true });
    expect(worldForLocation("/lab/white-cmj-acc-grf/white-s000", {}, "laboratory").world).toBe("performance");
    expect(worldForLocation("/lab/skillcorner-opendata/1", { view: "overview" }, "football").world).toBe("match");
    expect(worldForLocation("/lab/x/y", { view: "matchlab" }).world).toBe("match");
  });

  it("round-trips recent-context hrefs into typed targets", () => {
    const target = targetFromHref("/lab/skillcorner-opendata/1996436?view=matchlab&t_ns=120000000000");
    expect(target).toEqual({ to: "/lab/skillcorner-opendata/1996436", search: { view: "matchlab", t_ns: "120000000000" } });
    expect(hrefOf(target)).toBe("/lab/skillcorner-opendata/1996436?view=matchlab&t_ns=120000000000");
  });
});

describe("sports hierarchy", () => {
  it("groups contests under their edition, competition and sport", () => {
    const tree = buildSportsTree([contest(), upstreamContest, seasonEdition, courtContest]);
    expect(tree.map((sport) => sport.sportId)).toEqual(["football", "basketball"]);
    const edition = tree[0]!.competitions[0]!.editions[0]!;
    expect(edition.contests).toHaveLength(2);
    expect(edition.readyContests).toBe(1);
    expect(edition.upstreamContests).toBe(1);
    expect(edition.ready).toBe(true);
  });

  it("derives team membership only from canonical team ids in contests", () => {
    const teams = teamsForContests([contest(), upstreamContest]);
    const auckland = teams.find((team) => team.teamId === "team-auckland");
    expect(auckland?.contests).toHaveLength(2);
    expect(auckland?.readyContests).toBe(1);
  });

  it("titles contests with the served score", () => {
    expect(contestTitle(contest())).toBe("Auckland FC 2–1 Macarthur FC");
  });
});

describe("human performance and search", () => {
  const datasets = [
    {
      dataset_id: "white-cmj-acc-grf",
      name: "White CMJ accelerometer + vGRF",
      domain: "laboratory",
      provider: "Zenodo",
      modalities: ["force", "imu"],
      ingested_modalities: ["force", "imu"],
      license: { identifier: "CC-BY-4.0", noncommercial_only: false },
      session_count: 67,
      stream_count: 1326,
      subject_count: 67,
      trial_count: 663,
    },
    {
      dataset_id: "dfl-sportec-idsse",
      name: "DFL/Sportec IDSSE — tracking",
      domain: "football",
      provider: "Hugging Face",
      modalities: ["tracking", "event"],
      ingested_modalities: ["tracking"],
      license: { identifier: "CC-BY-4.0", noncommercial_only: false },
      session_count: 1,
      stream_count: 3,
      subject_count: 40,
      trial_count: 2,
    },
  ] as unknown as DatasetSummary[];

  it("lists only signal-modality datasets as studies", () => {
    const studies = buildStudies(datasets, []);
    expect(studies.map((study) => study.datasetId)).toEqual(["white-cmj-acc-grf"]);
    expect(studies[0]!.ready).toBe(false);
    expect(studies[0]!.readySessions).toBe(0);
  });

  it("uses per-session artifact and grain readiness instead of stream counts", () => {
    const session = (sessionId: string, stages: CatalogResourceView["stages"]) => ({
      resource_kind: "performance_session",
      resource_id: `white-cmj-acc-grf/${sessionId}`,
      label: sessionId,
      dataset_ids: ["white-cmj-acc-grf"],
      session_id: sessionId,
      stages,
    }) as CatalogResourceView;
    const studies = buildStudies(datasets, [
      session("white-s000", READY),
      session("white-s001", { ...READY, materialized: "not_materialized", ready: "not_ready" }),
    ]);

    expect(studies[0]!.readySessions).toBe(1);
    expect(studies[0]!.ready).toBe(true);
  });

  it("searches metadata and ranks ready contests first", () => {
    const hits = searchCatalog([contest(), upstreamContest, seasonEdition], buildStudies(datasets, []), "auckland");
    expect(hits[0]?.kind).toBe("contest");
    expect(hits[0]?.ready).toBe(true);
    expect(hits.some((hit) => hit.kind === "team" && hit.title === "Auckland FC")).toBe(true);
    expect(searchCatalog([], buildStudies(datasets, []), "cmj")[0]?.world).toBe("performance");
  });
});
