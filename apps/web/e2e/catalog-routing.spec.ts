import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test("Data Library filters by sport and keeps provider as a provenance facet", async ({ page }) => {
  const nonCatalogReads: string[] = [];
  const browserErrors: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.startsWith("/api/") && !pathname.startsWith("/api/catalog/") && pathname !== "/api/serving/status") {
      nonCatalogReads.push(pathname);
    }
  });
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto("/catalog");
  await expect(page.getByRole("heading", { name: "Data Library" })).toBeVisible();
  await page.getByLabel("Search data library").fill("Perth Glory");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByLabel("Search data library").fill("");
  await page.getByLabel("World").selectOption("__human__");
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await expect(page.getByText("Preparation eligible: register")).toBeVisible();
  await page.getByLabel("World").selectOption("basketball");
  await page.getByRole("main", { name: "Data Library" }).getByLabel("Rights").selectOption("noncommercial");
  await expect(page.locator("tbody tr")).toHaveCount(0);
  await page.getByRole("main", { name: "Data Library" }).getByLabel("Rights").selectOption("all");
  await page.getByLabel("Provider").selectOption("SportsDataverse");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody tr")).toContainText("NBA");
  await expect(page.getByText("Provider: SportsDataverse")).toBeVisible();
  await page.screenshot({ path: "test-results/catalog-library.png" });
  expect(nonCatalogReads).toEqual([]);
  expect(browserErrors).toEqual([]);
});

test("semantic capabilities route to each ready analysis surface", async ({ page }) => {
  const destinations: Array<{
    name: string;
    pathname: string;
    query: [string, string];
  }> = [
    { name: "MatchLab", pathname: "/lab/skillcorner-opendata/1925299", query: ["view", "matchlab"] },
    { name: "GameLab", pathname: "/games", query: ["edition", "sdv:nba:2026"] },
    { name: "SeasonLab", pathname: "/season", query: ["edition", "skillcorner:edition:870"] },
    {
      name: "Basketball spatial",
      pathname: "/basketball",
      query: ["contest", "skillcorner-basketball:contest:acb-1"],
    },
    { name: "Performance lab", pathname: "/lab/white-cmj-acc-grf/cmj-1", query: ["view", "overview"] },
  ];

  for (const destination of destinations) {
    await page.goto("/catalog");
    const link = page.locator("tbody").getByRole("link", { name: destination.name, exact: true }).first();
    if (destination.name === "GameLab") await expect(link).toHaveAttribute("href", /edition/);
    await link.click();
    await expect.poll(() => new URL(page.url()).pathname).toBe(destination.pathname);
    expect(new URL(page.url()).searchParams.get(destination.query[0])).toBe(destination.query[1]);
  }
});
