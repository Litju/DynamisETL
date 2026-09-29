import AxeBuilder from "@axe-core/playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { expectCleanConsole, probe } from "./helpers";

/**
 * RES-121 real-data acceptance: SkillCorner A-League 2024/25 season aggregates
 * served from the materialized PLAYER_SEASON artifacts. Nothing is mocked.
 */
const OUT = path.resolve(process.cwd(), "../../output/playwright/res-121/final");
const TAGGART = "skillcorner-opendata/211";
const BUGARIJA = "skillcorner-opendata/966112";

async function capture(page: Page, name: string) {
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

function search(page: Page): URLSearchParams {
  return new URL(page.url()).searchParams;
}

test("RES-121 SeasonLab real-data acceptance walkthrough", async ({ page }) => {
  const console = probe(page);
  const api: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) api.push(`${url.pathname}${url.search}`);
  });

  // 1 — A-League 2024/25 loads from the RES-120 artifacts.
  await page.goto("/season");
  await expect(page.getByRole("heading", { name: /268 players · 406 season rows/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Physical/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tab", { name: /Off-ball runs/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Passing/ })).toBeVisible();
  // Discovery reads identity rows only: no profile before a player is chosen.
  expect(api.filter((url) => url.includes("/profile"))).toEqual([]);

  // 2 — Perth Glory → Adam Taggart.
  await page.getByLabel("Team", { exact: true }).selectOption({ label: "Perth Glory" });
  await page.getByRole("button", { name: /^Adam Taggart/ }).click();
  const masthead = page.getByRole("region", { name: "Selected player" });
  await expect(masthead.getByRole("heading", { name: "Adam Taggart" })).toBeVisible();
  await expect(masthead).toContainText("Center Forward rows, A-League 2024/2025");
  expect(search(page).get("player")).toBe(TAGGART);

  // 3 — Physical metrics ranked against 74 Center Forward rows, with TIP/OTIP.
  await expect(page.getByRole("button", { name: /^Total distance: 10,515 m, rank 23 \/ 74, P70/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^PSV-99: 28\.83 km\/h/ })).toBeVisible();
  const split = page.getByRole("heading", { name: "In possession vs out of possession" });
  await split.scrollIntoViewIfNeeded();
  await expect(split).toBeVisible();
  await capture(page, "01-taggart-physical-1440x900.png");

  // 8 — source, method, grain and coverage stay visible.
  const evidence = page.getByRole("complementary", { name: "Metric evidence" });
  await expect(evidence).toContainText("PLAYER_SEASON");
  await expect(evidence).toContainText("subject × team × competition_edition × position_group");
  await expect(evidence).toContainText("406 (reconciled)");
  await expect(evidence).toContainText("above 60 minutes");
  await expect(evidence).toContainText("skillcorner-season-metrics/1");
  await expect(evidence).toContainText("MIT");

  // 4 — Off-ball runs.
  await page.getByRole("tab", { name: /Off-ball runs/ }).click();
  await expect(masthead.getByRole("heading", { name: "Adam Taggart" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Runs in behind:/ })).toBeVisible();
  await expect(evidence).toContainText("per 30 min TIP");
  await capture(page, "02-taggart-obr-1440x900.png");

  // 5 — Passing.
  await page.getByRole("tab", { name: /Passing/ }).click();
  await expect(page.getByRole("button", { name: /^Completion:/ })).toBeVisible();
  await capture(page, "03-taggart-passing-1440x900.png");

  // 6 — Compare two players with the same denominator.
  await page.getByRole("tab", { name: /Physical/ }).click();
  await page.getByPlaceholder("Search a player…").fill("Bugarija");
  await page.getByRole("option", { name: /Adam Bugarija/ }).click();
  await expect(page.getByText("same denominator · 74 rows")).toBeVisible();
  expect(search(page).get("compare")).toBe(BUGARIJA);
  const compareProfile = api.find((url) => url.includes("/profile") && url.includes(encodeURIComponent(BUGARIJA)));
  expect(compareProfile).toContain("population_position_group=Center");
  await capture(page, "04-taggart-vs-bugarija-1440x900.png");

  // 9 — the deep link reproduces the analytical context after reload.
  const deepLink = page.url();
  await page.reload();
  await expect(masthead.getByRole("heading", { name: "Adam Taggart" })).toBeVisible();
  await expect(page.getByText("same denominator · 74 rows")).toBeVisible();
  expect(page.url()).toBe(deepLink);

  // Back/Forward walks the analytical history.
  await page.goBack();
  await expect(page.getByText("same denominator · 74 rows")).toHaveCount(0);
  await page.goForward();
  await expect(page.getByText("same denominator · 74 rows")).toBeVisible();

  // 7 — link to a materialized MatchLab match only through identity authority.
  await expect(evidence).toContainText("No materialized match proves this player's participation");
  await page.getByRole("button", { name: /^Adam Bugarija/ }).click();
  await expect(masthead.getByRole("heading", { name: "Adam Bugarija" })).toBeVisible();
  await expect(evidence).toContainText("Brisbane Roar FC vs Perth Glory");
  const matchLink = evidence.getByRole("link", { name: "Open Match World with player selected" });
  await expect(matchLink).toBeVisible();
  await capture(page, "05-bugarija-match-linkage-1440x900.png");
  await matchLink.click();
  await expect(page).toHaveURL(/\/lab\/skillcorner-opendata\/1925299\?.*subject=966112.*view=matchlab|\/lab\/skillcorner-opendata\/1925299\?.*view=matchlab.*subject=966112/);

  // 10 — season aggregates never became frame/match data: no dense reads, no transport.
  await page.goBack();
  await expect(masthead.getByRole("heading", { name: "Adam Bugarija" })).toBeVisible();
  await expect(page.getByTestId("playhead-ns")).toHaveCount(0);
  const seasonDense = api.filter(
    (url) => url.includes("/window") && !url.includes("1925299"),
  );
  expect(seasonDense).toEqual([]);

  await expectCleanConsole(console);
});

for (const [width, height] of [
  [1600, 1000],
  [1440, 900],
  [1366, 768],
] as const) {
  test(`RES-121 SeasonLab composition ${width}×${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto(
      `/season?team=team-6db2746c59daa23a45580196&player=${encodeURIComponent(TAGGART)}&pos=Center+Forward&compare=${encodeURIComponent(BUGARIJA)}`,
    );
    await expect(page.getByText("same denominator · 74 rows")).toBeVisible();
    const main = page.getByRole("main", { name: "Season analysis" });
    const box = await main.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThan(width * 0.5);
    await capture(page, `06-seasonlab-${width}x${height}.png`);
  });
}

test("RES-121 SeasonLab axe (real data)", async ({ page }) => {
  await page.goto(
    `/season?team=team-6db2746c59daa23a45580196&player=${encodeURIComponent(TAGGART)}&pos=Center+Forward&compare=${encodeURIComponent(BUGARIJA)}`,
  );
  await expect(page.getByText("same denominator · 74 rows")).toBeVisible();
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.nodes.length}`)).toEqual([]);
});
