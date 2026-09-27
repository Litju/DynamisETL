import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  SeasonEditionView,
  SeasonFamilyView,
  SeasonProfileView,
  SeasonRowPage,
  SeasonRowView,
} from "@/api/types";
import { createAppRouter } from "@/router";

vi.mock("echarts", () => ({
  init: () => ({
    setOption: () => undefined,
    resize: () => undefined,
    dispose: () => undefined,
    getOption: () => ({}),
    on: () => undefined,
  }),
}));

const EDITION: SeasonEditionView = {
  dataset_id: "skillcorner-opendata",
  provider: "SkillCorner / PySport",
  sport_id: "football",
  sport_name: "Football",
  competition_id: "competition-a",
  competition_name: "A-League",
  edition_id: "edition-a",
  edition_label: "2024/2025",
  measurement_class: "SOURCE_DERIVED",
  inclusion_rule: "Only performances above 60 minutes.",
  glossary_url: null,
  registry_version: "skillcorner-season-metrics/1",
  license: {
    policy_id: "p",
    identifier: "MIT",
    status: "declared",
    attribution_required: true,
    noncommercial_only: false,
    share_alike: false,
    redistribution: "conditional",
    local_only: false,
    restrictions: [],
    notice: "MIT; attribution required",
  },
  families: [
    {
      family: "physical",
      label: "Physical",
      artifact_id: "season-physical",
      row_count: 3,
      checksum_sha256: "0".repeat(64),
      run_id: "run-1",
      grain_kind: "PLAYER_SEASON",
      grain_axes: ["subject", "team", "competition_edition", "position_group"],
      source_revision: "rev",
      source_file_key: "physical.csv",
      source_population_rows: 3,
      match_count_column: "count_match",
    },
    {
      family: "obr",
      label: "Off-ball runs",
      artifact_id: "season-obr",
      row_count: 3,
      checksum_sha256: "1".repeat(64),
      run_id: "run-1",
      grain_kind: "PLAYER_SEASON",
      grain_axes: ["subject", "team", "competition_edition", "position_group"],
      source_revision: "rev",
      source_file_key: "obr.csv",
      source_population_rows: 3,
      match_count_column: "performance_included_count",
    },
  ],
};

function row(subject: string, name: string, team: string, position: string, matches: number): SeasonRowView {
  return {
    subject_id: subject,
    player_name: name,
    player_short_name: null,
    team_id: team,
    team_name: team === "team-perth" ? "Perth Glory Football Club" : "Sydney FC",
    position_group: position,
    matches,
    values: {},
  };
}

const ROSTER = [
  row("sc/211", "Adam Taggart", "team-perth", "Center Forward", 24),
  row("sc/966112", "Adam Bugarija", "team-perth", "Center Forward", 4),
  row("sc/7", "Sam Sydney", "team-sydney", "Midfield", 10),
];

function familyView(family: "physical" | "obr"): SeasonFamilyView {
  return {
    edition: EDITION,
    family: EDITION.families.find((item) => item.family === family)!,
    metrics: [
      {
        metric_id: `skillcorner.${family}.psv99`,
        column: family === "physical" ? "psv99" : "behindrun_count_p30tip",
        family,
        label: family === "physical" ? "PSV-99" : "Runs in behind",
        group: family === "physical" ? "Peak speed" : "Volume",
        unit: family === "physical" ? "km/h" : "count",
        basis: family === "physical" ? "season value" : "per 30 min TIP",
        definition: "definition",
        split: null,
        base: null,
        exposure: false,
        higher_is: "more",
      },
    ],
    population_rows: 3,
    population_subjects: 3,
    teams: [
      { team_id: "team-perth", display_name: "Perth Glory Football Club", rows: 2 },
      { team_id: "team-sydney", display_name: "Sydney FC", rows: 1 },
    ],
    position_groups: [
      { position_group: "Center Forward", rows: 2 },
      { position_group: "Midfield", rows: 1 },
    ],
  };
}

function profile(subject: string, family: string): SeasonProfileView {
  const base = ROSTER.find((item) => item.subject_id === subject)!;
  const column = family === "physical" ? "psv99" : "behindrun_count_p30tip";
  const value = subject === "sc/211" ? 28.83 : 24.88;
  return {
    edition: EDITION,
    family: EDITION.families.find((item) => item.family === family)!,
    row: { ...base, values: { [column]: value } },
    population: {
      scope: "position",
      label: "Center Forward rows, A-League 2024/2025",
      team_id: null,
      position_group: "Center Forward",
      min_matches: null,
      rows: 2,
      unit_of_analysis: "player × team × position-group season row",
      selected_row_in_population: true,
    },
    metrics: [
      {
        metric_id: `skillcorner.${family}.${column}`,
        column,
        value,
        rank: subject === "sc/211" ? 1 : 2,
        percentile: subject === "sc/211" ? 100 : 50,
        valid_n: 2,
        population_minimum: 24.88,
        population_median: 26.855,
        population_maximum: 28.83,
      },
    ],
    percentile_method: "inclusive",
    rank_method: "rank 1 = largest",
    caveats: ["descriptive"],
  };
}

const requests: string[] = [];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function installFetchStub(): void {
  requests.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, "http://localhost");
      requests.push(`${url.pathname}${url.search}`);
      const path = url.pathname;
      if (path === "/api/season/editions") return json([EDITION]);
      const family = path.match(/families\/(physical|obr)/)?.[1] as "physical" | "obr" | undefined;
      if (family && path.endsWith(`/families/${family}`)) return json(familyView(family));
      if (family && path.endsWith("/rows")) {
        const page: SeasonRowPage = { total: ROSTER.length, limit: 1000, offset: 0, metrics: [], rows: ROSTER };
        return json(page);
      }
      if (family && path.endsWith("/profile")) {
        return json(profile(url.searchParams.get("subject_id") ?? "", family));
      }
      if (path.endsWith("/links")) {
        return json({
          subject_id: url.searchParams.get("subject_id"),
          identity_authority: "provider_identity_crosswalk(entity_kind=subject)",
          provider_namespace: null,
          provider_player_ids: [],
          appearances: [],
          team_contest_ids: ["contest-1"],
        });
      }
      if (path === "/api/catalog/sports/matches") return json([]);
      return json({ detail: `unhandled ${path}` }, 404);
    }),
  );
}

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("SeasonLab", () => {
  beforeEach(() => installFetchStub());
  afterEach(() => vi.unstubAllGlobals());

  it("opens on the edition overview and makes the edition durable", async () => {
    const router = renderAt("/season");
    expect(await screen.findByText("3 players · 3 season rows")).toBeInTheDocument();
    expect((router.state.location.search as Record<string, string>).edition).toBe("edition-a");
    // Discovery is identity-only: no profile is requested before a player is chosen.
    expect(requests.some((request) => request.includes("/profile"))).toBe(false);
  });

  it("restores a player profile and its explicit denominator from a deep link", async () => {
    renderAt("/season?edition=edition-a&team=team-perth&player=sc%2F211&pos=Center+Forward");
    const masthead = await screen.findByRole("region", { name: "Selected player" });
    expect(within(masthead).getByRole("heading", { name: "Adam Taggart" })).toBeInTheDocument();
    expect(within(masthead).getByText("Center Forward rows, A-League 2024/2025")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PSV-99: 28.83 km\/h, rank 1 \/ 2, P100/ })).toBeInTheDocument();
    expect(await screen.findByText(/No materialized match proves this player's participation/)).toBeInTheDocument();
  });

  it("commits player and family changes to history", async () => {
    const user = userEvent.setup();
    const router = renderAt("/season?edition=edition-a&team=team-perth");
    await user.click(await screen.findByRole("button", { name: /Adam Bugarija/ }));
    expect(await screen.findByRole("heading", { name: "Adam Bugarija" })).toBeInTheDocument();
    expect((router.state.location.search as Record<string, string>).player).toBe("sc/966112");

    await user.click(screen.getByRole("tab", { name: /Off-ball runs/ }));
    expect(await screen.findByRole("button", { name: /Runs in behind/ })).toBeInTheDocument();
    expect((router.state.location.search as Record<string, string>).family).toBe("obr");

    router.history.back();
    expect(await screen.findByRole("button", { name: /PSV-99/ })).toBeInTheDocument();
  });

  it("ranks a comparison against the first player's population", async () => {
    renderAt("/season?edition=edition-a&player=sc%2F211&compare=sc%2F966112");
    expect(await screen.findByText("same denominator · 2 rows")).toBeInTheDocument();
    const compareRequest = requests.find(
      (request) => request.includes("/profile") && request.includes("subject_id=sc%2F966112"),
    );
    expect(compareRequest).toContain("population_position_group=Center%20Forward");
  });
});
