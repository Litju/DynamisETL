import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { DFL, SC, expectCleanConsole, probe, waitForPitch } from "./helpers";

const OUT = path.resolve(process.cwd(), "../../output/playwright/res-113/final");

async function capture(page: Page, name: string) {
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

async function cameraTuple(pitch: Locator) {
  return {
    x: await pitch.getAttribute("data-camera-x"),
    y: await pitch.getAttribute("data-camera-height"),
    z: await pitch.getAttribute("data-camera-z"),
  };
}

test("RES-113 §21–22 real DFL and SkillCorner hybrid Field evidence", async ({ page }) => {
  const console = probe(page);

  await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300020000000&tactical=live`);
  const pitch = await waitForPitch(page);
  const panel = page.getByTestId("tactical-tabpanel");
  await expect(pitch).toHaveAttribute("data-camera-mode", "tactical-map");
  await expect(pitch).toHaveAttribute("data-camera-projection", "orthographic");
  await expect(pitch).toHaveAttribute("data-shadow-enabled", "false");
  await expect.poll(async () => Number(await pitch.getAttribute("data-v3-unit-count"))).toBeGreaterThan(0);
  await expect(panel).toContainText("Possession and ball context");
  await expect(panel).toContainText("DEF / MID / ATT");
  await expect.poll(async () => page.locator('[data-testid="pitch-canvas"] [data-testid="field-functional-unit-label"]').count()).toBeGreaterThan(0);
  await expect(panel).toContainText("DEF↔MID gap");
  await expect(page.getByRole("button", { name: "Occupied area" })).toHaveAttribute("aria-pressed", "false");

  const pitchLengthM = Number(await pitch.getAttribute("data-pitch-length-m"));
  const pitchWidthM = Number(await pitch.getAttribute("data-pitch-width-m"));
  const fittedHeightM = Number(await pitch.getAttribute("data-orthographic-frustum-height-m"));
  const pitchBounds = await pitch.boundingBox();
  expect(pitchLengthM).toBeGreaterThan(0);
  expect(pitchWidthM).toBeGreaterThan(0);
  expect(pitchBounds).not.toBeNull();
  expect(fittedHeightM).toBeGreaterThan(pitchWidthM);
  const fittedWidthM = fittedHeightM * pitchBounds!.width / pitchBounds!.height;
  expect(fittedWidthM / pitchLengthM).toBeGreaterThanOrEqual(1.04);
  expect(fittedWidthM / pitchLengthM).toBeLessThanOrEqual(1.15);
  await capture(page, "01-dfl-tactical-map-default-structure.png");

  await page.getByRole("tab", { name: "Structure" }).click();
  await expect(panel).toContainText("principal axis");
  await expect(panel).toContainText("major/minor 1σ");
  await capture(page, "02-dfl-functional-units-and-inter-line-gaps.png");

  await page.locator('#tactical-tabpanel button[title="Select this source-tracked player in Field and Pose"]').first().click();
  await expect.poll(async () => await pitch.getAttribute("data-selected-player-id")).not.toBe("");
  const mapCamera = await cameraTuple(pitch);
  await page.getByRole("button", { name: "Focus selected" }).click();
  await expect.poll(async () => await pitch.getAttribute("data-camera-x")).not.toBe(mapCamera.x);
  await page.getByRole("button", { name: "Reset camera" }).click();
  await expect(pitch).toHaveAttribute("data-camera-x", mapCamera.x!);
  await expect(pitch).toHaveAttribute("data-camera-z", mapCamera.z!);

  await page.getByRole("tab", { name: "Relations" }).click();
  await page.getByRole("button", { name: "Stable graph" }).click();
  await expect.poll(async () => Number(await pitch.getAttribute("data-v3-stable-edge-count"))).toBeGreaterThan(0);
  await expect(panel).toContainText("Stable incident Delaunay edges only");
  await page.getByRole("button", { name: "Local triangles" }).click();
  await expect.poll(async () => Number(await pitch.getAttribute("data-v3-stable-triangle-count"))).toBeGreaterThan(0);
  await expect(panel).toContainText("Only stable triangles incident to the selected player are exposed.");
  await capture(page, "03-dfl-selected-local-graph-and-triangles.png");

  await page.getByRole("tab", { name: "Space" }).click();
  await page.getByLabel("Scalar field mode").selectOption("heatmap");
  await page.getByRole("button", { name: "Influence" }).click();
  await expect.poll(async () => Number(await pitch.getAttribute("data-overlay-influence-cells"))).toBeGreaterThan(0);
  await capture(page, "04-dfl-flat-scalar-field.png");
  await page.getByLabel("Scalar field mode").selectOption("elevation");
  await page.getByRole("button", { name: "Structure Lift" }).click();
  await expect(pitch).toHaveAttribute("data-camera-mode", "structure-lift");
  await expect(pitch).toHaveAttribute("data-camera-projection", "orthographic");
  await expect(pitch).toHaveAttribute("data-shadow-enabled", "true");
  await expect.poll(async () => await pitch.getAttribute("data-scalar-surface-ready")).toBe("true");
  await expect.poll(async () => Number(await pitch.getAttribute("data-scalar-surface-vertices"))).toBeGreaterThan(0);
  await expect(page.getByTestId("analytical-elevation-disclaimer")).toHaveAttribute("aria-label", /scientific domain 0–5 s/);
  await expect(panel).toContainText("ANALYTICAL ELEVATION · NOT PHYSICAL HEIGHT");
  await capture(page, "05-dfl-structure-lift-analytical-elevation-shadow.png");

  await page.getByRole("button", { name: "Tactical Map" }).click();
  await expect(pitch).toHaveAttribute("data-camera-mode", "tactical-map");
  await expect(pitch).toHaveAttribute("data-camera-projection", "orthographic");
  await expect(pitch).toHaveAttribute("data-shadow-enabled", "false");
  await page.getByRole("button", { name: "Reset camera" }).click();
  await expect(pitch).toHaveAttribute("data-camera-x", mapCamera.x!);
  await expect(pitch).toHaveAttribute("data-camera-z", mapCamera.z!);
  await capture(page, "06-dfl-instant-tactical-map-return.png");

  await page.goto(`${SC}?view=field&stream=tracking-period-1&subject=11897&t_ns=120000000000&tactical=live`);
  const skillCornerPitch = await waitForPitch(page);
  await expect(skillCornerPitch).toHaveAttribute("data-camera-mode", "tactical-map");
  await expect(skillCornerPitch).toHaveAttribute("data-camera-projection", "orthographic");
  await expect(skillCornerPitch).toHaveAttribute("data-shadow-enabled", "false");
  await expect.poll(async () => Number(await skillCornerPitch.getAttribute("data-v3-unit-count"))).toBeGreaterThan(0);
  await expect(page.getByTestId("tactical-tabpanel")).toContainText("DEF / MID / ATT");
  await capture(page, "07-skillcorner-tactical-map-default-and-structure.png");
  await page.getByRole("tab", { name: "Space" }).click();
  await page.getByLabel("Scalar field mode").selectOption("heatmap");
  await page.getByRole("button", { name: "Influence" }).click();
  await expect.poll(async () => Number(await skillCornerPitch.getAttribute("data-overlay-influence-cells"))).toBeGreaterThan(0);
  await capture(page, "08-skillcorner-flat-scalar-field.png");
  await page.getByLabel("Scalar field mode").selectOption("elevation");
  await page.getByRole("button", { name: "Structure Lift" }).click();
  await expect(skillCornerPitch).toHaveAttribute("data-camera-mode", "structure-lift");
  await expect(skillCornerPitch).toHaveAttribute("data-camera-projection", "orthographic");
  await expect(skillCornerPitch).toHaveAttribute("data-shadow-enabled", "true");
  await expect.poll(async () => await skillCornerPitch.getAttribute("data-scalar-surface-ready")).toBe("true");
  await expect.poll(async () => Number(await skillCornerPitch.getAttribute("data-scalar-surface-vertices"))).toBeGreaterThan(0);
  await expect(page.getByTestId("analytical-elevation-disclaimer")).toHaveAttribute("aria-label", /scientific domain 0–5 s/);
  await capture(page, "09-skillcorner-structure-lift-analytical-elevation-shadow.png");

  await page.goto(`${SC}?view=split&stream=tracking-period-1&subject=11897&t_ns=120000000000&tactical=live`);
  const splitPitch = await waitForPitch(page);
  const pose = page.getByTestId("pose-canvas");
  await expect(splitPitch).toHaveAttribute("data-camera-mode", "tactical-map");
  await expect(splitPitch).toHaveAttribute("data-camera-projection", "orthographic");
  await expect(splitPitch).toHaveAttribute("data-shadow-enabled", "false");
  await expect(pose).toHaveAttribute("data-renderer-ready", "true");
  await expect(pose).toHaveAttribute("data-camera-projection", "perspective");
  await expect.poll(async () => Number(await splitPitch.getAttribute("data-v3-unit-count"))).toBeGreaterThan(0);
  const originalSubject = await pose.getAttribute("data-selected-player-id");
  const fieldPlayers = page.locator('[data-testid="pitch-canvas"] button[aria-label^="Select player "]');
  const availableFieldPlayers = await fieldPlayers.evaluateAll((buttons) => buttons.map((button, index) => ({
    label: button.getAttribute("aria-label") ?? "",
    index,
  })));
  const nextFieldPlayer = availableFieldPlayers.find((item) => item.label.slice("Select player ".length) !== originalSubject);
  expect(nextFieldPlayer, "split Field exposes another tracked player to select").toBeDefined();
  const fieldSubject = nextFieldPlayer!.label.slice("Select player ".length);
  await fieldPlayers.nth(nextFieldPlayer!.index).click();
  await expect(splitPitch).toHaveAttribute("data-selected-player-id", fieldSubject);
  await expect(pose).toHaveAttribute("data-selected-player-id", fieldSubject);
  await page.getByRole("button", { name: "Controls", exact: true }).click();
  const subjectSelect = page.getByLabel("Pose subject");
  const firstPoseSubject = (await subjectSelect.locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value)))
    .find((subjectId) => subjectId !== fieldSubject);
  expect(firstPoseSubject, "Pose exposes a second source participant").toBeDefined();
  await subjectSelect.selectOption(firstPoseSubject!);
  await expect(pose).toHaveAttribute("data-selected-player-id", firstPoseSubject!);
  await expect(splitPitch).toHaveAttribute("data-selected-player-id", firstPoseSubject!);
  await page.getByRole("button", { name: "Close controls", exact: true }).click();
  await capture(page, "10-skillcorner-field-orthographic-pose-3d-synchronized.png");

  await expectCleanConsole(console);
});
