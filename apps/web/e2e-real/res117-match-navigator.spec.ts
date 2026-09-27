import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { expectCleanConsole, probe, waitForPitch } from "./helpers";

const OUT = path.resolve(process.cwd(), "../../output/playwright/res-117/final");

async function capture(page: Page, name: string) {
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

async function openMatchFromNavigator(page: Page, matchId: string) {
  const row = page.locator(`[data-testid="match-navigator-match"][data-match-id="${matchId}"]`);
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: /^Open / }).click();
}

test("RES-117 metadata-only corpus browser exposes all 20 SkillCorner matches and capabilities", async ({ page }) => {
  const console = probe(page);
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) apiRequests.push(`${url.pathname}${url.search}`);
  });

  await page.goto("/lab");
  await expect(page.getByRole("heading", { name: "Match Navigator", exact: true })).toBeVisible();
  await expect(page.getByText("Browse the sports corpus and local readiness", { exact: false })).toBeVisible();
  await page.getByLabel("Competition").selectOption({ label: "A-League" });
  await page.getByLabel("Season / Edition").selectOption({ label: "2024/2025" });
  await expect(page.getByTestId("match-navigator-match")).toHaveCount(20);
  await expect(page.getByLabel("Team").locator("option")).toHaveCount(14);

  const brisbane = page.locator('[data-testid="match-navigator-match"][data-match-id="1925299"]');
  const sydney = page.locator('[data-testid="match-navigator-match"][data-match-id="1996435"]');
  const auckland = page.locator('[data-testid="match-navigator-match"][data-match-id="1996436"]');
  await expect(brisbane).toContainText("Brisbane Roar FC");
  await expect(brisbane).toContainText(" vs ");
  await expect(brisbane).toContainText("Perth Glory");
  await expect(brisbane).toContainText("Partly materialized");
  await expect(brisbane.getByTestId("pose-capability")).toHaveCount(1);
  await expect(sydney).toContainText("Sydney Football Club");
  await expect(sydney).toContainText(" vs ");
  await expect(sydney.getByTestId("pose-capability")).toHaveCount(1);
  await expect(auckland.getByTestId("pose-capability")).toHaveCount(0);
  await expect(auckland).toContainText("Available at source");

  await page.getByLabel("Team").selectOption({ index: 1 });
  expect(await page.getByTestId("match-navigator-match").count()).toBeGreaterThan(0);
  expect(await page.getByTestId("match-navigator-match").count()).toBeLessThan(20);
  await page.getByLabel("Team").selectOption("");
  await expect(page.getByTestId("match-navigator-match")).toHaveCount(20);
  await expect(page.getByRole("button", { name: /^Prepare / }).first()).toBeVisible();
  await page.getByRole("button", { name: /^Prepare / }).first().click();
  await expect(page.getByRole("status").filter({ hasText: "Prepare required" })).toBeVisible();

  await expect(apiRequests.filter((url) => /\/window(?:\?|$)|\/tactical\/series\//.test(url))).toEqual([]);
  await capture(page, "01-metadata-only-corpus.png");
  await expectCleanConsole(console);
});

test("RES-117 atomic match, period, player, time and history transitions use MatchLab URL state", async ({ page }) => {
  const console = probe(page);
  const apiRequests: string[] = [];
  const denseRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return;
    apiRequests.push(`${url.pathname}${url.search}`);
    if (/\/api\/artifacts\/[^/]+\/window$/.test(url.pathname)) denseRequests.push(url.pathname);
  });
  const [skillcorner, poseSkillcorner, noPoseSkillcorner] = await Promise.all(
    ["1925299", "1996435", "1996436"].map(async (id) =>
      (await page.request.get(`/api/catalog/datasets/skillcorner-opendata/sessions/${id}`)).json(),
    ),
  );
  const oldSkillCornerArtifacts = [skillcorner, poseSkillcorner, noPoseSkillcorner].flatMap((session) =>
    session.streams.flatMap((stream: { sample_artifact_ids: string[] }) => stream.sample_artifact_ids),
  );
  const noPoseExpectedPlayerIds = noPoseSkillcorner.participants.map((player: { subject_id: string }) => player.subject_id);
  const dfl = await (await page.request.get("/api/catalog/datasets/dfl-sportec-idsse/sessions/DFL-MAT-J03WPY")).json();
  const dflArtifactIds = dfl.streams.flatMap((stream: { sample_artifact_ids: string[] }) => stream.sample_artifact_ids);
  const dflExpectedPlayerIds = dfl.participants.map((player: { subject_id: string }) => player.subject_id);

  await page.goto("/lab");
  await page.getByLabel("Competition").selectOption({ label: "A-League" });
  await page.getByLabel("Season / Edition").selectOption({ label: "2024/2025" });
  await openMatchFromNavigator(page, "1925299");
  await expect(page).toHaveURL(/lab\/skillcorner-opendata\/1925299/);
  await waitForPitch(page);
  const pose = page.getByTestId("pose-canvas");
  await expect(pose).toHaveAttribute("data-renderer-ready", "true");
  await expect(pose).toHaveAttribute("data-canonical-time-ns", "440000000");
  await expect(page.getByText(/No valid Pose sample/)).toHaveCount(0);
  await expect(page).toHaveURL(/view=matchlab/);
  await expect(page).toHaveURL(/trial=period_1/);
  await capture(page, "02-skillcorner-1925299-pose.png");

  await page.getByRole("button", { name: "Open MatchLab explorer" }).click();
  await expect(page.getByTestId("match-navigator").last()).toBeVisible();
  await expect(page.getByLabel("Match period").locator('option[value="period_1"]')).toContainText("Events source");
  await page.getByLabel("Match period").selectOption("period_2");
  await expect(page).toHaveURL(/trial=period_2/);
  await expect(page).toHaveURL(/stream=tracking-period-2/);
  const player = page.getByLabel("Match player");
  const nextPlayer = await player.locator("option").nth(2).getAttribute("value");
  expect(nextPlayer).toBeTruthy();
  await player.selectOption(nextPlayer!);
  await expect(page).toHaveURL(new RegExp(`subject=${encodeURIComponent(nextPlayer!)}`));

  const timestamp = "2800000000000";
  await page.getByLabel("Canonical timestamp in nanoseconds").fill(timestamp);
  await page.getByRole("button", { name: "Go", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`t_ns=${timestamp}`));
  await page.getByLabel("Range start in nanoseconds").fill("2800000000000");
  await page.getByLabel("Range end in nanoseconds").fill("2820000000000");
  await page.getByRole("button", { name: "Apply range" }).click();
  await expect(page).toHaveURL(/from_ns=2800000000000/);
  await expect(page).toHaveURL(/to_ns=2820000000000/);

  const slider = page.getByTestId("transport-timeline");
  await slider.focus();
  await slider.press("ArrowRight");
  await expect.poll(async () => new URL(page.url()).searchParams.get("t_ns")).not.toBe(timestamp);
  const deepLink = page.url();
  await page.reload();
  await expect(page).toHaveURL(deepLink);
  if (await page.getByRole("button", { name: "Open MatchLab explorer" }).count()) {
    await page.getByRole("button", { name: "Open MatchLab explorer" }).click();
  }
  await expect(page.getByLabel("Match period")).toHaveValue("period_2");
  await expect(page.getByLabel("Match player")).toHaveValue(nextPlayer!);
  await expect(page.getByLabel("Range start in nanoseconds")).toHaveValue("2800000000000");
  await expect(page.getByLabel("Range end in nanoseconds")).toHaveValue("2820000000000");
  await capture(page, "03-skillcorner-period-player-time-range.png");
  const selectedAtReload = await page.getByLabel("Match player").inputValue();
  await page.getByLabel("Filter matches").last().fill("1996435");
  await openMatchFromNavigator(page, "1996435");
  await expect(page).toHaveURL(/lab\/skillcorner-opendata\/1996435/);
  await waitForPitch(page);
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await expect(page.getByLabel("Match player")).not.toHaveValue(selectedAtReload);
  await capture(page, "04-skillcorner-1996435-pose.png");

  await page.getByLabel("Filter matches").last().fill("1996436");
  await openMatchFromNavigator(page, "1996436");
  await expect(page).toHaveURL(/lab\/skillcorner-opendata\/1996436/);
  const noPoseField = await waitForPitch(page);
  await expect(page.getByTestId("matchlab-pose-unavailable")).toBeVisible();
  await expect(page.getByTestId("pose-canvas")).toHaveCount(0);
  const noPosePlayerIds = await page.getByLabel("Match player").locator("option").evaluateAll(
    (options) => options.map((option) => (option as HTMLOptionElement).value).filter(Boolean),
  );
  expect([...noPosePlayerIds].sort()).toEqual([...noPoseExpectedPlayerIds].sort());
  await page.getByLabel("Match player").selectOption(noPoseExpectedPlayerIds[0]);
  await expect(noPoseField).toHaveAttribute("data-selected-player-id", noPoseExpectedPlayerIds[0]);
  await expect(page).toHaveURL(new RegExp(`subject=${encodeURIComponent(noPoseExpectedPlayerIds[0]!)}`));
  await capture(page, "05-skillcorner-1996436-no-pose.png");

  const navigator = page.getByTestId("match-navigator").last();
  await navigator.getByLabel("Sport").selectOption("");
  await navigator.getByLabel("Competition").selectOption("");
  await navigator.getByLabel("Season / Edition").selectOption("");
  await page.getByLabel("Filter matches").last().fill("DFL-MAT-J03WPY");
  const denseStart = denseRequests.length;
  const apiStart = apiRequests.length;
  await openMatchFromNavigator(page, "DFL-MAT-J03WPY");
  await expect(page).toHaveURL(/lab\/dfl-sportec-idsse\/DFL-MAT-J03WPY/);
  await waitForPitch(page);
  await expect(page.getByTestId("matchlab-pose-unavailable")).toBeVisible();
  const dflPlayerIds = await page.getByLabel("Match player").locator("option").evaluateAll(
    (options) => options.map((option) => (option as HTMLOptionElement).value).filter(Boolean),
  );
  expect([...dflPlayerIds].sort()).toEqual([...dflExpectedPlayerIds].sort());
  expect(dfl.streams.some((stream: { sample_artifact_ids: string[] }) => stream.sample_artifact_ids.some((id: string) => dflArtifactIds.includes(id)))).toBe(true);
  await expect.poll(() => apiRequests.slice(apiStart).some((url) => url.includes("/api/tactical/artifacts?") && url.includes("dataset_id=dfl-sportec-idsse"))).toBe(true);
  const dflTacticalRequests = apiRequests.slice(apiStart).filter((url) => url.includes("/api/tactical/artifacts?"));
  expect(dflTacticalRequests.every((url) => url.includes("dataset_id=dfl-sportec-idsse"))).toBe(true);
  expect(denseRequests.slice(denseStart).some((url) => oldSkillCornerArtifacts.some((id: string) => url.includes(id)))).toBe(false);
  await capture(page, "06-dfl-after-skillcorner.png");

  await page.getByRole("button", { name: "Navigator back" }).click();
  await expect(page).toHaveURL(/lab\/skillcorner-opendata\/1996436/);
  await expect(page.getByTestId("matchlab-pose-unavailable")).toBeVisible();
  await page.getByRole("button", { name: "Navigator forward" }).click();
  await expect(page).toHaveURL(/lab\/dfl-sportec-idsse\/DFL-MAT-J03WPY/);
  expect(await page.getByLabel("Match player").inputValue()).toBe("");
  expect(new URL(page.url()).searchParams.get("subject")).toBeNull();
  expect(denseRequests.some((url) => dflArtifactIds.some((id: string) => url.includes(id)))).toBe(true);
  const currentNavigator = page.getByTestId("match-navigator").last();
  await currentNavigator.getByLabel("Sport").selectOption("");
  await currentNavigator.getByLabel("Competition").selectOption("");
  await currentNavigator.getByLabel("Season / Edition").selectOption("");
  await page.getByLabel("Filter matches").last().fill("1925299");
  await openMatchFromNavigator(page, "1925299");
  await expect(page).toHaveURL(/lab\/skillcorner-opendata\/1925299/);
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await expectCleanConsole(console);
});
