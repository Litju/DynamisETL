import { expect, test, type Page } from "@playwright/test";

import { installApiMocks } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

function watch(page: Page) {
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
  return { nonCatalogReads, browserErrors };
}

test("Data Browser answers what exists from metadata only", async ({ page }) => {
  const seen = watch(page);
  await page.goto("/catalog");
  await expect(page).toHaveURL(/\/data$/);
  await expect(page.getByRole("heading", { name: "Sports", level: 1 })).toBeVisible();
  const hierarchy = page.getByRole("navigation", { name: "Data hierarchy" });
  await expect(hierarchy.getByRole("link", { name: /Football/ })).toBeVisible();
  await expect(hierarchy.getByRole("link", { name: /Basketball/ })).toBeVisible();
  // Provider is provenance on the competition, never the destination.
  await expect(page.getByText("A-League")).toBeVisible();
  await expect(page.getByRole("link", { name: /2025-26/ }).first()).toBeVisible();

  await hierarchy.getByRole("link", { name: /Force/ }).click();
  await expect(page.getByRole("heading", { name: "Force", level: 1 })).toBeVisible();
  await expect(page.getByText("White CMJ accelerometer + vGRF")).toBeVisible();

  await page.goto("/data?domain=sports&provider=SportsDataverse");
  await expect(page.getByText("NBA")).toBeVisible();
  await expect(page.getByText("A-League")).toHaveCount(0);
  await page.screenshot({ path: "test-results/data-browser.png" });
  expect(seen.nonCatalogReads).toEqual([]);
  expect(seen.browserErrors).toEqual([]);
});

test("semantic capabilities route into the pertinent World", async ({ page }) => {
  // Match World: edition context -> ready contest.
  await page.goto("/data/edition/skillcorner:edition:870");
  await expect(page.getByRole("heading", { name: /A-League/, level: 1 })).toBeVisible();
  await page.getByRole("link", { name: /Open Match World/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/lab/skillcorner-opendata/1925299");
  expect(new URL(page.url()).searchParams.get("view")).toBe("matchlab");
  await expect(page.getByRole("button", { name: /Match World/ })).toBeVisible();

  // Season World from the same edition.
  await page.goto("/data/edition/skillcorner:edition:870");
  await page.getByRole("link", { name: "Open Season World" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/season");
  expect(new URL(page.url()).searchParams.get("edition")).toBe("skillcorner:edition:870");

  // Game World from an edition whose grain is play-by-play.
  await page.goto("/data/edition/sdv:nba:2026");
  await page.getByRole("link", { name: "Open Game World" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/games");
  expect(new URL(page.url()).searchParams.get("edition")).toBe("sdv:nba:2026");

  // Basketball tracking opens the court (Match World), never football MatchLab.
  await page.goto("/data/edition/skillcorner-basketball:edition:2026");
  await page.getByRole("link", { name: /Open court/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/basketball");
  expect(new URL(page.url()).searchParams.get("contest")).toBe("skillcorner-basketball:contest:acb-1");

  // Performance World: study -> session -> trial.
  await page.goto("/performance?dataset=white-cmj-acc-grf&session=cmj-1");
  await expect(page.getByRole("heading", { name: "White CMJ accelerometer + vGRF", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: /Open first trial/ }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe("/lab/white-cmj-acc-grf/cmj-1");
  expect(new URL(page.url()).searchParams.get("trial")).toBe("cmj-1-arms-t00");
});

test("Match World Back returns to the catalog, including from a direct deep link", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?view=matchlab");
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(/\/data$/u);
  await expect(page.getByRole("heading", { name: "Sports", level: 1 })).toBeVisible();

  await page.goto("/data/edition/skillcorner:edition:870?tab=matches&status=ready");
  await page.getByRole("link", { name: /Open Match World/ }).click();
  await expect(page).toHaveURL(/\/lab\/skillcorner-opendata\/1925299/u);
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page).toHaveURL(/\/data\/edition\/skillcorner:edition:870\?tab=matches&status=ready/u);
});

test("the command palette searches metadata and switches Worlds", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Research", level: 1 })).toBeVisible();
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  await expect(palette.getByRole("combobox", { name: "Command search" })).toBeFocused();
  await page.keyboard.type("perth");
  await expect(palette.getByRole("option", { name: /Brisbane Roar FC 0–1 Perth Glory/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect.poll(() => new URL(page.url()).pathname).toBe("/lab/skillcorner-opendata/1925299");
  await expect(palette).toBeHidden();
});
