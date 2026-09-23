import { expect, test } from "@playwright/test";

import {
  DFL,
  SC,
  evidence,
  expectCleanConsole,
  measurePlayback,
  playheadNs,
  probe,
  waitForPitch,
} from "./helpers";

/**
 * RES-112 real-data Field acceptance (no interception). Requires
 * `dynamis-demo-prepare` to report READY for the local corpus.
 */

test.describe("SkillCorner Field", () => {
  test("opens on the first canonical frame and every surface agrees", async ({ page }) => {
    const console = probe(page);
    await page.goto(`${SC}?view=field`);
    const canvas = await waitForPitch(page);
    await expect(page).toHaveURL(/t_ns=0(&|$)/);
    expect(await playheadNs(page)).toBe(0n);
    await expect(canvas).toHaveAttribute("data-drawn-frame-ns", "0");
    await expect(page.getByTestId("pitch-frame-summary")).toContainText("players");
    await expectCleanConsole(console);
  });

  test("hull overlay is the drawn frame, in team colours, and playback keeps one renderer", async ({ page }) => {
    const console = probe(page);
    await page.goto(`${SC}?view=field`);
    const canvas = await waitForPitch(page);
    await expect(canvas).toHaveAttribute("data-overlay-hulls", "2");
    const drawn = await canvas.getAttribute("data-drawn-frame-ns");
    expect(drawn).toBe("0");

    const before = console.api.length;
    await page.getByRole("button", { name: "Play" }).click();
    const playback = await measurePlayback(page, 5_000);
    await page.getByRole("button", { name: "Pause playback" }).click();
    const during = console.api.slice(before);
    // F-03: one Pixi application for the whole playback.
    expect(playback.distinctCanvases).toBe(1);
    // T-02 / F-04: tactical reads follow chunk handoffs, never animation frames.
    const tacticalReads = during.filter((line) => line.includes("/api/tactical/series/"));
    expect(tacticalReads.length).toBeLessThanOrEqual(6);
    const after = await playheadNs(page);
    expect(after).not.toBeNull();
    expect(after!).toBeGreaterThan(2_000_000_000n);
    // Pause commits the time durably.
    await expect(page).toHaveURL(new RegExp(`t_ns=${after}`));
    await expect(canvas).toHaveAttribute("data-overlay-hulls", "2");
    const frame = await canvas.getAttribute("data-drawn-frame-ns");
    expect(BigInt(frame!)).toBeLessThanOrEqual(after!);
    expect(after! - BigInt(frame!)).toBeLessThan(150_000_000n);
    await evidence(page, "field-sc-after-play");
    await expectCleanConsole(console);
  });

  test("timeline seek lands on an exact frame in a later chunk", async ({ page }) => {
    const console = probe(page);
    await page.goto(`${SC}?view=field`);
    const canvas = await waitForPitch(page);
    const timeline = page.getByTestId("transport-timeline");
    await timeline.focus();
    await page.keyboard.press("End");
    await expect(page).toHaveURL(/t_ns=30229\d+/);
    const end = await playheadNs(page);
    await expect(canvas).toHaveAttribute("data-drawn-frame-ns", String(end));
    await page.keyboard.press("Home");
    await expect(page).toHaveURL(/t_ns=0(&|$)/);
    await expect(canvas).toHaveAttribute("data-drawn-frame-ns", "0");
    await expectCleanConsole(console);
  });

  test("territory layer toggles live on the same frame", async ({ page }) => {
    const console = probe(page);
    await page.goto(`${SC}?view=field&t_ns=120000000000`);
    const canvas = await waitForPitch(page);
    await expect(canvas).toHaveAttribute("data-drawn-frame-ns", "120000000000");
    const territory = page.getByRole("button", { name: /Territory/ });
    await territory.click();
    await expect(territory).toHaveAttribute("aria-pressed", "true");
    await expect.poll(async () => Number(await canvas.getAttribute("data-overlay-territory-cells"))).toBeGreaterThan(10);
    await evidence(page, "field-sc-territory");
    await territory.click();
    await expect(canvas).toHaveAttribute("data-overlay-territory-cells", "0");
    await expectCleanConsole(console);
  });

  test("entity selection uses its own key and survives a chunk handoff", async ({ page }) => {
    const console = probe(page);
    await page.goto(`${SC}?view=field&t_ns=26000000000&entity=ball`);
    await waitForPitch(page);
    await expect(page.getByTestId("pitch-selection")).toContainText("Ball");
    const history = await page.evaluate(() => window.history.length);
    await page.getByRole("button", { name: "Play" }).click();
    await page.waitForTimeout(3_000);
    await page.getByRole("button", { name: "Pause playback" }).click();
    expect(await playheadNs(page)).toBeGreaterThan(27_481_000_000n);
    await expect(page).toHaveURL(/entity=ball/);
    await expect(page).not.toHaveURL(/subject=ball/);
    await expect(page.getByTestId("pitch-selection")).toContainText("Ball");
    expect(await page.evaluate(() => window.history.length)).toBe(history);
    await expectCleanConsole(console);
  });
});

test.describe("DFL Field", () => {
  test("playback starts from the first canonical frame (1.02 s) and advances", async ({ page }) => {
    const console = probe(page);
    await page.goto(`${DFL}?view=field`);
    const canvas = await waitForPitch(page);
    await expect(page).toHaveURL(/t_ns=1020000000(&|$)/);
    await expect(canvas).toHaveAttribute("data-drawn-frame-ns", "1020000000");
    await page.getByRole("button", { name: "Play" }).click();
    await page.waitForTimeout(3_000);
    await page.getByRole("button", { name: "Pause playback" }).click();
    expect(await playheadNs(page)).toBeGreaterThan(3_000_000_000n);
    await expect(page.getByTestId("playback-ended")).toHaveCount(0);
    await expectCleanConsole(console);
  });

  test("switching period resolves time into the new period's span", async ({ page }) => {
    const console = probe(page);
    await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=60000000000`);
    await waitForPitch(page);
    await page.getByRole("link", { name: /tracking-period-2/ }).click();
    await expect(page).toHaveURL(/stream=tracking-period-2/);
    await expect(page).toHaveURL(/t_ns=3721660000000/);
    const canvas = await waitForPitch(page);
    await expect(canvas).toHaveAttribute("data-drawn-frame-ns", "3721660000000");
    await expectCleanConsole(console);
  });
});
