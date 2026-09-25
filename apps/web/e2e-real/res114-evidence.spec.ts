import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { DFL, SC, expectCleanConsole, probe, waitForPitch } from "./helpers";

const OUT = path.resolve(process.cwd(), "../../output/playwright/res-114/final");

async function capture(page: Page, name: string) {
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

async function assertWorkstationRatios(page: Page, width: number) {
  const bounds = await Promise.all([
    page.getByTestId("matchlab-field-panel").boundingBox(),
    page.getByTestId("matchlab-pose-viewport").boundingBox(),
    page.getByTestId("matchlab-analysis-dashboard").boundingBox(),
  ]);
  expect(bounds.every(Boolean), `${width}px workstation columns are visible`).toBe(true);
  const field = bounds[0]!;
  const pose = bounds[1]!;
  const dashboard = bounds[2]!;
  const total = field.width + pose.width + dashboard.width;
  expect(field.width / total).toBeGreaterThan(0.46);
  expect(field.width / total).toBeLessThan(0.50);
  expect(pose.width / total).toBeGreaterThan(0.28);
  expect(pose.width / total).toBeLessThan(0.32);
  expect(dashboard.width / total).toBeGreaterThan(0.20);
  expect(dashboard.width / total).toBeLessThan(0.24);
  expect(pose.width).toBeGreaterThan(300);
  expect(dashboard.width).toBeGreaterThan(250);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("RES-114 §19 real SkillCorner MatchLab composition and responsive evidence", async ({ page }) => {
  const console = probe(page);
  const url = `${SC}?view=matchlab&stream=tracking-period-1&subject=11897&t_ns=120000000000&tactical=live`;

  for (const [width, height] of [[1600, 1000], [1440, 900], [1366, 768]] as const) {
    await page.setViewportSize({ width, height });
    await page.goto(url);
    const field = await waitForPitch(page);
    const pose = page.getByTestId("pose-canvas");
    await expect(pose).toHaveAttribute("data-renderer-ready", "true");
    await expect(pose).toHaveAttribute("data-selected-player-id", "11897");
    await expect(pose).toHaveAttribute("data-canonical-time-ns", "120000000000");
    await expect(field).toHaveAttribute("data-camera-mode", "tactical-map");
    await expect(field).toHaveAttribute("data-camera-projection", "orthographic");
    await expect(field).toHaveAttribute("data-canonical-time-ns", "120000000000");
    await expect(page.getByTestId("matchlab-analysis-dashboard")).toBeVisible();
    await expect(page.getByTestId("matchlab-context-spine")).toContainText("Source native");
    await expect(page.getByRole("button", { name: "Play", exact: true })).toBeVisible();
    await expect(page.locator("footer[aria-label='Transport and timeline']")).toHaveCount(1);
    await expect(page.locator("[data-testid='matchlab-canvas-root'] canvas")).toHaveCount(1);
    await assertWorkstationRatios(page, width);
    await capture(page, `01-skillcorner-matchlab-${width}x${height}.png`);
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${SC}?view=matchlab&stream=tracking-period-1&t_ns=120000000000&tactical=live`);
  const defaultField = await waitForPitch(page);
  const defaultPose = page.getByTestId("pose-canvas");
  await expect.poll(async () => await defaultField.getAttribute("data-selected-player-id")).not.toBe("");
  const defaultSubjectId = await defaultField.getAttribute("data-selected-player-id");
  await expect(defaultPose).toHaveAttribute("data-selected-player-id", defaultSubjectId!);
  await expect(defaultPose).toHaveAttribute("data-canonical-time-ns", await defaultField.getAttribute("data-canonical-time-ns"));
  await expect(page.getByLabel("Dashboard selected player")).toHaveValue(defaultSubjectId!);
  await page.getByRole("button", { name: "Open MatchLab explorer" }).click();
  await expect(page.getByRole("heading", { name: "Session explorer" })).toBeVisible();
  await page.getByRole("button", { name: "Close MatchLab explorer" }).last().click();
  await capture(page, "00-skillcorner-matchlab-source-selected-default-1440x900.png");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(url);
  const field = await waitForPitch(page);
  const pose = page.getByTestId("pose-canvas");
  const initialTimeNs = BigInt((await field.getAttribute("data-canonical-time-ns"))!);
  const parsePlayheadNs = async () => {
    const text = await page.getByTestId("playhead-ns").textContent();
    return BigInt(/(-?\d+) ns/.exec(text ?? "")?.[1] ?? "0");
  };
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect.poll(parsePlayheadNs).toBeGreaterThan(initialTimeNs);
  await page.getByRole("button", { name: "Pause playback" }).click();
  const playedTimeNs = (await field.getAttribute("data-canonical-time-ns"))!;
  await expect(pose).toHaveAttribute("data-canonical-time-ns", playedTimeNs);
  const dashboardPlayer = page.getByLabel("Dashboard selected player");
  const fieldPlayerIds = await page.locator('[data-testid="pitch-canvas"] button[aria-label^="Select player "]').evaluateAll(
    (buttons) => buttons.map((button) => button.getAttribute("aria-label")?.slice("Select player ".length) ?? ""),
  );
  const fieldSelection = fieldPlayerIds.find((id) => id !== "11897");
  expect(fieldSelection, "real Field exposes another tracked participant").toBeTruthy();
  await dashboardPlayer.selectOption(fieldSelection!);
  await expect(field).toHaveAttribute("data-selected-player-id", fieldSelection!);
  await expect(pose).toHaveAttribute("data-selected-player-id", fieldSelection!);
  await expect(dashboardPlayer).toHaveValue(fieldSelection!);

  const nextFieldSelection = fieldPlayerIds.find((id) => id !== "11897" && id !== fieldSelection);
  expect(nextFieldSelection, "Field can change the canonical player selection").toBeTruthy();
  await page.locator(`[aria-label="Select player ${nextFieldSelection}"]`).click();
  await expect(field).toHaveAttribute("data-selected-player-id", nextFieldSelection!);
  await expect(pose).toHaveAttribute("data-selected-player-id", nextFieldSelection!);
  await expect(dashboardPlayer).toHaveValue(nextFieldSelection!);

  await page.getByRole("button", { name: "Controls", exact: true }).click();
  const poseSubjects = page.getByLabel("Pose subject");
  const poseSubjectIds = await poseSubjects.locator("option").evaluateAll(
    (options) => options.map((option) => (option as HTMLOptionElement).value).filter(Boolean),
  );
  const poseSelection = poseSubjectIds.find((id) => id !== fieldSelection);
  expect(poseSelection, "real Pose source exposes a second selected subject").toBeTruthy();
  await poseSubjects.selectOption(poseSelection!);
  await expect(field).toHaveAttribute("data-selected-player-id", poseSelection!);
  await expect(pose).toHaveAttribute("data-selected-player-id", poseSelection!);
  await expect(page.getByRole("tab", { name: "Biomechanics", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Selected joint", exact: true }).click();
  await page.getByLabel("Select Pose landmark").selectOption("lKnee");
  await expect(page.getByRole("tab", { name: "Selected joint", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByTestId("pose-body-local-shortcut").click();
  await expect(page.getByTestId("matchlab-context-spine")).toContainText("body-local display");
  await capture(page, "02-skillcorner-matchlab-body-local-1440x900.png");
  await page.getByRole("tab", { name: "Quality", exact: true }).click();
  await expect(page.getByTestId("pose-analysis-pane")).toContainText("Quality");
  await capture(page, "03-skillcorner-matchlab-pose-quality-1440x900.png");
  await page.getByLabel("Dashboard selected player").selectOption("11897");
  await expect(field).toHaveAttribute("data-selected-player-id", "11897");
  await expect(pose).toHaveAttribute("data-selected-player-id", "11897");

  await page.getByRole("tab", { name: "Tactical", exact: true }).click();
  await page.getByRole("tab", { name: "Relations", exact: true }).click();
  await expect(page.getByTestId("tactical-tabpanel")).toContainText("Stable");
  await capture(page, "04-skillcorner-matchlab-relations-1440x900.png");

  await page.goto(`${SC}?view=matchlab&stream=tracking-period-1&subject=11897&t_ns=120000000000&from_ns=110000000000&to_ns=130000000000&tactical=report`);
  await waitForPitch(page);
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await page.getByRole("tab", { name: "Biomechanics", exact: true }).click();
  await page.getByRole("tab", { name: "Selected joint", exact: true }).click();
  await page.getByLabel("Select Pose landmark").selectOption("lKnee");
  await expect(page.getByRole("tab", { name: "Selected joint", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "Combined report", exact: true }).click();
  await expect(page.getByTestId("tactical-report")).toContainText('"report": "dynamis.tactical.v1"');
  await expect(page.getByRole("region", { name: "Exact Pose range report" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Exact Pose range report" })).toContainText("lKnee");
  await capture(page, "05-skillcorner-matchlab-report-1440x900.png");
  await expectCleanConsole(console);
});

test("RES-114 §19 real DFL MatchLab keeps Tactical Map and states Pose unavailability", async ({ page }) => {
  const console = probe(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${DFL}?view=matchlab&stream=tracking-period-1&t_ns=300020000000&tactical=live`);
  const field = await waitForPitch(page);
  await expect(field).toHaveAttribute("data-camera-mode", "tactical-map");
  await expect(field).toHaveAttribute("data-camera-projection", "orthographic");
  await expect(page.getByTestId("matchlab-pose-unavailable")).toBeVisible();
  await expect(page.getByTestId("matchlab-pose-unavailable")).toContainText("no Pose stream");
  await expect(page.getByTestId("matchlab-context-spine")).toContainText("Pose unavailable");
  await expect(page.getByTestId("tactical-tabpanel")).toContainText("DEF / MID / ATT");
  const playerSelect = page.getByLabel("Dashboard selected player");
  const trackedSubject = await playerSelect.locator("option").nth(1).getAttribute("value");
  expect(trackedSubject).toBeTruthy();
  await playerSelect.selectOption(trackedSubject!);
  await expect(field).toHaveAttribute("data-selected-player-id", trackedSubject!);
  await expect(page.getByTestId("matchlab-pose-unavailable")).toBeVisible();
  await expect(playerSelect).toHaveValue(trackedSubject!);
  await assertWorkstationRatios(page, 1440);
  await capture(page, "04-dfl-matchlab-pose-unavailable-1440x900.png");
  await expectCleanConsole(console);
});
