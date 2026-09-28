import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { expectCleanConsole, probe } from "./helpers";

const EDITION = "edition-ebf871f2a9cd29912d68880e";
const PERTH = "team-6db2746c59daa23a45580196";
const BUGARIJA = "skillcorner-opendata/966112";
const TAGGART = "skillcorner-opendata/211";
const OUT = path.resolve(process.cwd(), "../../output/playwright/res-129/final");

async function capture(page: Page, viewport: string, name: string) {
  const directory = path.join(OUT, viewport);
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, name), animations: "disabled" });
}

const viewports = [
  { label: "1600x1000", width: 1600, height: 1000 },
  { label: "1440x900", width: 1440, height: 900 },
  { label: "1366x768", width: 1366, height: 768 },
] as const;

for (const viewport of viewports) {
  test(`RES-129 football entity surfaces at ${viewport.label}`, async ({ page }) => {
    const console = probe(page);
    const denseReads: string[] = [];
    page.on("request", (request) => {
      const pathname = new URL(request.url()).pathname;
      if (/\/window$|\/tactical\/(?:series|artifacts)/u.test(pathname)) denseReads.push(pathname);
    });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });

    await page.goto(`/data/edition/${EDITION}?tab=teams`);
    await expect(page.getByRole("heading", { name: /A-League 2024\/2025/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Perth Glory Football Club/ }).first()).toBeVisible();
    await capture(page, viewport.label, "10-a-league-teams.png");

    await page.goto(`/data/edition/${EDITION}?tab=players`);
    await expect(page.getByRole("link", { name: /Adam Taggart/ })).toBeVisible();
    await capture(page, viewport.label, "11-a-league-players.png");

    await page.goto(`/data/edition/${EDITION}?tab=season`);
    await expect(page.getByText("Metric families", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: /Off-ball runs/ })).toBeVisible();
    await capture(page, viewport.label, "12-a-league-season-data.png");

    await page.goto(`/data/team/${PERTH}?edition=${EDITION}`);
    await expect(page.getByRole("heading", { name: "Perth Glory Football Club", exact: true })).toBeVisible();
    await expect(page.getByText(/registered contests ready/)).toBeVisible();
    await expect(page.getByRole("link", { name: /Adam Bugarija/ })).toBeVisible();
    await capture(page, viewport.label, "13-team-perth-glory.png");

    await page.goto(`/data/player/${encodeURIComponent(BUGARIJA)}?edition=${EDITION}`);
    await expect(page.getByRole("heading", { name: "Adam Bugarija", exact: true })).toBeVisible();
    await expect(page.getByText("Off-ball runs data is unavailable for this player.", { exact: true })).toBeVisible();
    await expect(page.getByText("Pose available", { exact: true })).toBeVisible();
    await expect(page.getByText("Match World ready", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open with player selected" })).toBeVisible();
    await capture(page, viewport.label, "14-player-adam-bugarija.png");

    await page.goto(`/data/player/${encodeURIComponent(TAGGART)}?edition=${EDITION}`);
    await expect(page.getByRole("heading", { name: "Adam Taggart", exact: true })).toBeVisible();
    await expect(page.getByText(/No materialized contest proves this player's participation/)).toBeVisible();
    await capture(page, viewport.label, "15-player-adam-taggart-unlinked.png");

    await page.goto(`/season?edition=${EDITION}&family=physical&team=${PERTH}&player=${encodeURIComponent(BUGARIJA)}`);
    await expect(page.getByRole("complementary", { name: "Metric evidence" }).getByRole("link", { name: "Open Match World with player selected" })).toBeVisible();
    await capture(page, viewport.label, "16-season-bugarija-match-linkage.png");

    expect(denseReads).toEqual([]);
    await expectCleanConsole(console);
  });
}

test("RES-129 canonical player continuity preserves exact Match and Season URLs", async ({ page }) => {
  const console = probe(page);
  const denseReads: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (/\/window$|\/tactical\/(?:series|artifacts)/u.test(pathname)) denseReads.push(pathname);
  });

  await page.goto(`/lab/skillcorner-opendata/1925299?view=matchlab&subject=966112`);
  await expect(page.getByRole("link", { name: /Season profile/ })).toBeVisible();
  const matchUrl = page.url();
  expect(new URL(matchUrl).searchParams.get("subject")).toBe("966112");

  const denseBeforeSeason = denseReads.length;
  await page.getByRole("link", { name: /Season profile/ }).click();
  await expect(page).toHaveURL(/\/season\?/u);
  await expect(new URL(page.url()).searchParams.get("player")).toBe(BUGARIJA);
  await expect(page.getByRole("complementary", { name: "Metric evidence" }).getByRole("link", { name: "Open Match World with player selected" })).toBeVisible();
  const seasonUrl = page.url();
  expect(denseReads.length).toBe(denseBeforeSeason);

  await page.reload();
  await expect(page.getByRole("complementary", { name: "Metric evidence" })).toContainText("Match linkage");
  expect(page.url()).toBe(seasonUrl);
  expect(denseReads.length).toBe(denseBeforeSeason);
  await page.goBack();
  await expect(page).toHaveURL(matchUrl);
  await expect(page.getByLabel("Dashboard selected player")).toHaveValue("966112");
  await page.goForward();
  await expect(page).toHaveURL(seasonUrl);

  await page.getByRole("complementary", { name: "Metric evidence" }).getByRole("link", { name: "Open Match World with player selected" }).click();
  await expect(page).toHaveURL(/\/lab\/skillcorner-opendata\/1925299\?/u);
  await expect(page.getByLabel("Dashboard selected player")).toHaveValue("966112");
  await page.waitForFunction(() => new URL(location.href).searchParams.has("t_ns"));
  const linkedMatchUrl = page.url();
  expect(new URL(linkedMatchUrl).searchParams.get("subject")).toBe("966112");
  expect(new URL(linkedMatchUrl).searchParams.get("view")).toBe("matchlab");
  await page.goBack();
  await expect(page).toHaveURL(seasonUrl);
  await page.goForward();
  await expect(page).toHaveURL(linkedMatchUrl);

  await expectCleanConsole(console);
});

test("RES-129 switching canonical players never carries the prior player values", async ({ page }) => {
  await page.goto(`/data/team/${PERTH}?edition=${EDITION}`);
  await page.getByRole("link", { name: /Adam Bugarija/ }).click();
  await expect(page.getByRole("heading", { name: "Adam Bugarija", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Perth Glory Football Club", exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Adam Taggart/ }).click();
  await expect(page.getByRole("heading", { name: "Adam Taggart", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Adam Bugarija", exact: true })).toHaveCount(0);
  await expect(page.getByText(/No materialized contest proves this player's participation/)).toBeVisible();
});

test("RES-129 reports unavailable Pose for a ready A-League match without Pose", async ({ page }) => {
  const console = probe(page);
  await page.goto("/lab/skillcorner-opendata/1996436?view=matchlab");
  await expect(page.getByTestId("matchlab-pose-unavailable")).toBeVisible();
  await expect(page.getByTestId("matchlab-pose-unavailable")).toContainText("Pose unavailable for this period");
  await expect(page.getByTestId("pose-canvas")).toHaveCount(0);
  await expectCleanConsole(console);
});
