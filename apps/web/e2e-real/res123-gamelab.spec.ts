import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import type { GameEditionView, GamePage, GamePlayPage, GameSummaryView } from "@/api/types";
import { expectCleanConsole, probe } from "./helpers";

const NBA_PROVIDER_GAME_ID = "401809243";
const NHL_PROVIDER_GAME_ID = "2025020001";

interface LocatedGame {
  readonly game: GameSummaryView;
  readonly offset: number;
}

test("RES-123 GameLab real NBA and NHL acceptance", async ({ page, request }) => {
  const console = probe(page);
  const editions = await getJson<GameEditionView[]>(request, "/api/games/editions");
  const nbaEdition = editions.find((edition) => edition.league_id === "nba");
  const nhlEdition = editions.find((edition) => edition.league_id === "nhl");
  expect(nbaEdition, "the accepted NBA edition is materialized").toBeDefined();
  expect(nhlEdition, "the accepted NHL edition is materialized").toBeDefined();
  if (!nbaEdition || !nhlEdition) return;

  const nba = await locateGame(request, nbaEdition, NBA_PROVIDER_GAME_ID);
  const nhl = await locateGame(request, nhlEdition, NHL_PROVIDER_GAME_ID);
  const nbaPlays = await getJson<GamePlayPage>(request, `/api/games/${nba.game.contest_id}/plays?limit=1000`);
  const nhlPlays = await getJson<GamePlayPage>(request, `/api/games/${nhl.game.contest_id}/plays?limit=1000`);
  expect(nbaPlays.rows.length).toBeGreaterThan(1);
  expect(nhlPlays.rows.length).toBeGreaterThan(1);

  await page.goto(`/games?edition=${encodeURIComponent(nbaEdition.edition_id)}`);
  await expect(page.getByRole("heading", { name: "GameLab" })).toBeVisible();
  await browseToGame(page, nba, NBA_PROVIDER_GAME_ID);
  await expect(page.getByTestId("gamelab")).toHaveAttribute("data-sport", "nba");
  await expect(page.getByLabel("Local-only source rights")).toBeVisible();
  await expect(page.getByRole("region", { name: "Game context" })).toContainText("Oklahoma City Thunder");
  await expect(page.getByRole("region", { name: "Game context" })).toContainText("Houston Rockets");
  await expect(page.getByRole("region", { name: "Game context" })).toContainText("125");
  await expect(page.getByRole("region", { name: "Game context" })).toContainText("PBP final 125–124 · agrees with schedule");
  await expect(page.getByRole("table", { name: "NBA players" })).toBeVisible();

  const firstNbaPlay = nbaPlays.rows[0]!;
  const secondNbaPlay = nbaPlays.rows[1]!;
  await selectPlay(page, firstNbaPlay);
  await expect(page.getByRole("heading", { name: firstNbaPlay.attributes.type_text as string })).toBeVisible();
  await expect(page.getByText(/Points attempted:/)).toBeVisible();
  await expect(page.getByLabel("NHL source lineup context")).toHaveCount(0);
  assertUrlPlay(page, firstNbaPlay);

  const selectedTeam = nba.game.teams[0]!;
  await page.getByRole("combobox", { name: "Selected team" }).selectOption(selectedTeam.team_id);
  await expect.poll(() => new URL(page.url()).searchParams.get("team")).toBe(selectedTeam.team_id);
  const firstNbaLink = page.url();
  await page.reload();
  await expect(page.locator(`[data-event-id="${firstNbaPlay.source_event_id}"]`)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("combobox", { name: "Selected team" })).toHaveValue(selectedTeam.team_id);

  await page.getByTestId("game-timeline").focus();
  await page.keyboard.press("ArrowDown");
  await expect.poll(() => new URL(page.url()).searchParams.get("event")).toBe(secondNbaPlay.source_event_id);
  const secondNbaLink = page.url();
  await page.goBack();
  await expect(page).toHaveURL(firstNbaLink);
  await page.goForward();
  await expect(page).toHaveURL(secondNbaLink);

  await page.getByRole("button", { name: "Team", exact: true }).click();
  const nbaTeamTable = page.getByRole("table", { name: "NBA teams" });
  await expect(nbaTeamTable).toBeVisible();
  await nbaTeamTable.getByRole("row").nth(1).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("team")).toMatch(/^team-/);

  const pageGames = await getJson<GamePage>(
    request,
    `/api/games?edition_id=${encodeURIComponent(nbaEdition.edition_id)}&limit=60&offset=${nba.offset}`,
  );
  const alternateGame = pageGames.rows.find((game) => game.contest_id !== nba.game.contest_id);
  expect(alternateGame, "another contest is available on the current page").toBeDefined();
  if (alternateGame) {
    await browseToGame(
      page,
      { game: alternateGame, offset: nba.offset },
      alternateGame.provider_game_id ?? alternateGame.contest_id,
    );
    await expect.poll(() => new URL(page.url()).searchParams.get("game")).toBe(alternateGame.contest_id);
    await page.goBack();
    await expect.poll(() => new URL(page.url()).searchParams.get("game")).toBe(nba.game.contest_id);
    await page.goForward();
    await expect.poll(() => new URL(page.url()).searchParams.get("game")).toBe(alternateGame.contest_id);
    await page.goBack();
    await expect.poll(() => new URL(page.url()).searchParams.get("game")).toBe(nba.game.contest_id);
  }

  await page.getByRole("combobox", { name: "Competition edition" }).selectOption(nhlEdition.edition_id);
  await browseToGame(page, nhl, NHL_PROVIDER_GAME_ID);
  await expect(page.getByTestId("gamelab")).toHaveAttribute("data-sport", "nhl");
  await expect(page.getByRole("region", { name: "Game context" })).toContainText("Florida Panthers");
  await expect(page.getByRole("region", { name: "Game context" })).toContainText("Chicago Blackhawks");
  await expect(page.getByRole("region", { name: "Game context" })).toContainText("PBP final 3–2 · agrees with schedule");
  await expect(page.getByRole("table", { name: "NHL skaters" })).toBeVisible();
  await expect(page.getByRole("table", { name: "NHL goalies" })).toBeVisible();
  await expect(page.getByRole("table", { name: "NBA players" })).toHaveCount(0);

  const firstNhlPlay = nhlPlays.rows[0]!;
  await selectPlay(page, firstNhlPlay);
  await expect(page.getByLabel("NHL source lineup context")).toBeVisible();
  await expect(page.getByLabel("NHL source lineup context")).toContainText("Brad Marchand");
  await expect(page.getByText(/Strength:/)).toBeVisible();
  assertUrlPlay(page, firstNhlPlay);
  const firstNhlLink = page.url();
  await page.reload();
  await expect(page.locator(`[data-event-id="${firstNhlPlay.source_event_id}"]`)).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("NHL source lineup context")).toContainText("Brad Marchand");
  await expect(page).toHaveURL(firstNhlLink);

  // Return to NBA through the edition control; no hockey player, event, clock,
  // team or provider extension may survive this new contest context.
  await page.getByRole("combobox", { name: "Competition edition" }).selectOption(nbaEdition.edition_id);
  await browseToGame(page, nba, NBA_PROVIDER_GAME_ID);
  await expect(page.getByTestId("gamelab")).toHaveAttribute("data-sport", "nba");
  await expect(page.getByLabel("NHL source lineup context")).toHaveCount(0);
  const params = new URL(page.url()).searchParams;
  expect(params.get("event")).toBeNull();
  expect(params.get("clock")).toBeNull();
  expect(params.get("player")).toBeNull();
  expect(params.get("team")).toBeNull();
  const finalNbaPlay = nbaPlays.rows[0]!;
  await selectPlay(page, finalNbaPlay);
  await expect(page.getByText(/Points attempted:/)).toBeVisible();
  await expect(page.getByLabel("NHL source lineup context")).toHaveCount(0);

  await expectCleanConsole(console);
});

test("RES-123 GameLab presents rights-restricted payload state", async ({ page, request }) => {
  const editions = await getJson<GameEditionView[]>(request, "/api/games/editions");
  const nbaEdition = editions.find((edition) => edition.league_id === "nba");
  expect(nbaEdition).toBeDefined();
  if (!nbaEdition) return;
  const nba = await locateGame(request, nbaEdition, NBA_PROVIDER_GAME_ID);
  const gamePath = `/api/games/${nba.game.contest_id}`;
  const restricted = async (route: import("@playwright/test").Route) =>
    route.fulfill({
      status: 451,
      contentType: "application/json",
      body: JSON.stringify({ detail: "This local-only source is blocked in public exposure.", state: "rights_restricted" }),
    });
  await page.route((url) => new URL(url).pathname === `${gamePath}/plays`, restricted);
  await page.route((url) => new URL(url).pathname === `${gamePath}/box`, restricted);
  await page.goto(`/games?edition=${encodeURIComponent(nbaEdition.edition_id)}&game=${encodeURIComponent(nba.game.contest_id)}`);
  await expect(page.getByLabel("Local-only source rights")).toBeVisible();
  await expect(page.locator('[data-state="rights"]')).toHaveCount(2);
  await expect(page.getByText("This game payload is blocked by source rights.", { exact: true })).toHaveCount(2);
});

test("RES-123 GameLab keeps schedule authority visible on an NBA score discrepancy", async ({ page, request }) => {
  const editions = await getJson<GameEditionView[]>(request, "/api/games/editions");
  const nbaEdition = editions.find((edition) => edition.league_id === "nba");
  expect(nbaEdition).toBeDefined();
  if (!nbaEdition) return;
  const mismatch = await locateGame(request, nbaEdition, "401871335");
  await page.goto(
    `/games?edition=${encodeURIComponent(nbaEdition.edition_id)}&game=${encodeURIComponent(mismatch.game.contest_id)}`,
  );
  await expect(page.getByRole("region", { name: "Game context" })).toContainText(
    "PBP final 116–108 · differs; schedule score shown",
  );
});

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `${path} returns real serving data`).toBeTruthy();
  return (await response.json()) as T;
}

async function locateGame(
  request: APIRequestContext,
  edition: GameEditionView,
  providerGameId: string,
): Promise<LocatedGame> {
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;
  while (offset < total) {
    const page = await getJson<GamePage>(
      request,
      `/api/games?edition_id=${encodeURIComponent(edition.edition_id)}&limit=1000&offset=${offset}`,
    );
    const found = page.rows.find((game) => game.provider_game_id === providerGameId);
    if (found) return { game: found, offset: page.offset };
    total = page.total;
    if (page.rows.length === 0) break;
    offset = page.offset + page.limit;
  }
  throw new Error(`${edition.competition_name} game ${providerGameId} was not served`);
}

async function browseToGame(page: Page, located: LocatedGame, providerGameId: string) {
  let offset = Number(new URL(page.url()).searchParams.get("offset") ?? "0");
  while (offset < located.offset) {
    await page.getByRole("button", { name: "Next games page" }).click();
    offset = Number(new URL(page.url()).searchParams.get("offset") ?? "0");
  }
  while (offset > located.offset) {
    await page.getByRole("button", { name: "Previous games page" }).click();
    offset = Number(new URL(page.url()).searchParams.get("offset") ?? "0");
  }
  const filter = page.getByRole("searchbox", { name: "Filter contests" });
  await filter.fill(providerGameId);
  const row = page.getByRole("table", { name: "NBA and NHL contests" }).getByRole("row").filter({ hasText: providerGameId });
  await expect(row).toBeVisible();
  await row.click();
  await filter.fill("");
  await expect.poll(() => new URL(page.url()).searchParams.get("game")).toBe(located.game.contest_id);
}

async function selectPlay(page: Page, play: GamePlayPage["rows"][number]) {
  await page.locator(`[data-testid="play-row"][data-event-id="${play.source_event_id}"]`).click();
  await expect.poll(() => new URL(page.url()).searchParams.get("event")).toBe(play.source_event_id);
  await expect.poll(() => new URL(page.url()).searchParams.get("period")).toBe(String(play.period_number));
  if (typeof play.source_clock?.clock === "string") {
    await expect.poll(() => new URL(page.url()).searchParams.get("clock")).toBe(play.source_clock.clock);
  }
  if (play.subject_id) {
    await expect.poll(() => new URL(page.url()).searchParams.get("player")).toBe(play.subject_id);
  }
}

function assertUrlPlay(page: Page, play: GamePlayPage["rows"][number]) {
  const params = new URL(page.url()).searchParams;
  expect(params.get("event")).toBe(play.source_event_id);
  expect(params.get("period")).toBe(String(play.period_number));
  expect(params.get("clock")).toBe(play.source_clock?.clock ?? null);
  if (play.subject_id) expect(params.get("player")).toBe(play.subject_id);
}
