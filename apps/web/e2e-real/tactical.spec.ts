import { expect, test, type Page } from "@playwright/test";

import { DFL, SC, evidence, expectCleanConsole, playheadNs, probe, waitForPitch } from "./helpers";

/**
 * RES-112 real-data Tactical Analysis acceptance: every tab on DFL (A/B/C/D
 * materialized) and SkillCorner (A/B/C; D/E unsupported by the source).
 */
function pane(page: Page) {
  return page.getByRole("region", { name: "Tactical Analysis" });
}

async function openTab(page: Page, name: string) {
  await pane(page).getByRole("tab", { name, exact: true }).click();
  await expect(page.getByTestId("tactical-tabpanel")).toHaveAttribute("data-view", name.toLowerCase());
}

test("DFL: every tactical tab shows real processor output or an explicit authority state", async ({ page }) => {
  const console = probe(page);
  await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300000000000`);
  await waitForPitch(page);
  const panel = page.getByTestId("tactical-tabpanel");
  await expect(page.getByTestId("tactical-context")).toContainText("00:05:00.000");

  // Live: one row per team, registered team names, units and class.
  await expect(panel.getByRole("table", { name: /Level A team geometry/ })).toBeVisible();
  await expect(panel).toContainText("1. FC Nürnberg");
  await expect(panel).toContainText("Fortuna Düsseldorf");
  await expect(panel).toContainText("Hull area");
  await expect(panel).toContainText(/pipeline-derived/i);
  await evidence(page, "field-dfl-live");

  // Space: deterministic territory and MODEL_ESTIMATED influence per team.
  await openTab(page, "Space");
  await expect(panel.getByRole("table", { name: /Level B territory/ })).toBeVisible();
  await expect(panel.getByRole("table", { name: /Level C influence/ })).toBeVisible();
  await expect(panel).toContainText(/model-estimated/i);
  await evidence(page, "field-dfl-space");

  // Shape: Level E is unsupported by the source authority.
  await openTab(page, "Shape");
  await expect(panel).toContainText("Unsupported by this source");
  await expect(panel).toContainText("level_e_shape_phase".replace("level_e_shape_phase", "unavailable"));

  // Range: explicit commit, then per-team statistics over exact rows.
  await openTab(page, "Range");
  await expect(panel).toContainText("No range is committed.");
  await panel.getByRole("button", { name: "Commit playhead ± 15 s" }).click();
  await expect(page).toHaveURL(/from_ns=285000000000/);
  await expect(page).toHaveURL(/to_ns=315000000000/);
  await expect(panel.getByRole("table", { name: /Length and width statistics per team/ })).toBeVisible();
  await expect(panel).toContainText(/\d+ exact rows/);
  await panel.getByRole("button", { name: "Clear range" }).click();
  await expect(page).not.toHaveURL(/from_ns=/);

  // Events: source-event snapshots in the 2-minute window; seek moves the playhead.
  await openTab(page, "Events");
  const events = panel.getByRole("list", { name: "Source events" });
  await expect(events).toBeVisible();
  const first = events.getByRole("button").first();
  await first.click();
  await expect(page).toHaveURL(/t_ns=\d+/);
  const seeked = await playheadNs(page);
  expect(seeked).not.toBeNull();
  expect(seeked!).toBeGreaterThanOrEqual(240_000_000_000n);
  expect(seeked!).toBeLessThan(360_000_000_000n);
  await evidence(page, "field-dfl-events");

  // Report: provenance for every materialized level.
  await openTab(page, "Report");
  const report = JSON.parse((await page.getByTestId("tactical-report").textContent()) ?? "{}");
  for (const level of ["A", "B", "C", "D"]) {
    expect(report.levels[level].status, level).toBe("available");
    expect(report.levels[level].artifacts[0].run_id, level).toMatch(/^run-/);
  }
  expect(report.levels.E.status).toBe("unsupported");
  await expectCleanConsole(console);
});

test("DFL: overlays for all three tactical layers are the drawn frame", async ({ page }) => {
  const console = probe(page);
  await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300020000000`);
  const canvas = await waitForPitch(page);
  // 300.020 s is on the DFL 40 ms frame grid (1.02 s + k * 40 ms).
  await expect(canvas).toHaveAttribute("data-drawn-frame-ns", "300020000000");
  await expect(canvas).toHaveAttribute("data-overlay-hulls", "2");
  await page.getByRole("button", { name: /Territory/ }).click();
  await expect.poll(async () => Number(await canvas.getAttribute("data-overlay-territory-cells"))).toBeGreaterThan(15);
  await page.getByRole("button", { name: /Influence/ }).click();
  await expect.poll(async () => Number(await canvas.getAttribute("data-overlay-influence-cells"))).toBeGreaterThan(100);
  await expect(page.getByText(/Influence: MODEL_ESTIMATED tiles · grid @ 00:0[45]:[05]\d/)).toBeVisible();
  await evidence(page, "field-dfl-all-layers");
  await expectCleanConsole(console);
});

test("SkillCorner: A/B/C available; events and shape explicitly unsupported", async ({ page }) => {
  const console = probe(page);
  await page.goto(`${SC}?view=field&stream=tracking-period-1&t_ns=120000000000`);
  await waitForPitch(page);
  const panel = page.getByTestId("tactical-tabpanel");
  await expect(panel.getByRole("table", { name: /Level A team geometry/ })).toBeVisible();
  await expect(panel).toContainText("Brisbane Roar FC");
  await openTab(page, "Space");
  await expect(panel.getByRole("table", { name: /Level C influence/ })).toBeVisible();
  await openTab(page, "Events");
  await expect(panel).toContainText("Unsupported by this source");
  await expect(panel).toContainText("no accepted local event or phase artifact");
  await evidence(page, "field-sc-events-unsupported");
  await openTab(page, "Shape");
  await expect(panel).toContainText("Unsupported by this source");
  // Keyboard: arrow keys move between tabs.
  await pane(page).getByRole("tab", { name: "Shape" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("tactical-tabpanel")).toHaveAttribute("data-view", "range");
  await expectCleanConsole(console);
});
