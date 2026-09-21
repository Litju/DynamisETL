import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

/**
 * Fixed-viewport acceptance evidence for presentation drift (never scientific
 * validation). The same routes are also used for optional pixel baselines.
 *
 * Comparing rendered pixels across platforms is noisy, so comparisons only run
 * when `VISUAL_REGRESSION=1` is set on a reference platform; the default CI run
 * captures the artifacts as attachments instead. Baselines live next to this
 * spec (`*.spec.ts-snapshots/`) and are refreshed with
 * `VISUAL_REGRESSION=1 pnpm test:e2e --update-snapshots`.
 */
const COMPARE = process.env.VISUAL_REGRESSION === "1";

const SCREENSHOT_DIR = process.env.ACCEPTANCE_SCREENSHOT_DIR;

const SHOTS: Array<{ name: string; route: string }> = [
  { name: "01-catalog.png", route: "/catalog" },
  {
    name: "02-session-overview.png",
    route: "/lab/skillcorner-opendata/1925299?view=overview&t_ns=50000000",
  },
  {
    name: "03-signals.png",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000",
  },
  {
    name: "04-field.png",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field",
  },
  {
    name: "05-pose.png",
    route: "/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0",
  },
  {
    name: "06-compare.png",
    route: "/compare?metric=pose.angular_rom.left_knee",
  },
  {
    name: "07-method-provenance.png",
    route: "/methods?metric=pose.angular_rom.left_knee&result=dm-pose-rom",
  },
  { name: "08-quality.png", route: "/quality" },
  { name: "09-runs.png", route: "/runs" },
];

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

for (const shot of SHOTS) {
  test(`visual: ${shot.name}`, async ({ page }, testInfo) => {
    const consoleMessages: string[] = [];
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      const entry = `${message.type()}: ${message.text()}`;
      consoleMessages.push(entry);
      if (message.type() === "error") consoleErrors.push(entry);
    });
    page.on("pageerror", (error) => {
      const entry = `pageerror: ${error.message}`;
      consoleMessages.push(entry);
      consoleErrors.push(entry);
    });
    await page.setViewportSize({ width: 1600, height: 1000 });
    await page.goto(shot.route);
    await page.waitForLoadState("networkidle");
    if (shot.route.includes("view=field")) {
      await expect(page.getByTestId("pitch-canvas")).toHaveAttribute(
        "data-renderer-ready",
        "true",
      );
    }
    if (shot.route.includes("view=pose")) {
      await expect(page.getByTestId("pose-canvas")).toHaveAttribute(
        "data-renderer-ready",
        "true",
      );
    }
    if (shot.route.includes("/methods")) {
      await expect(page.getByTestId("lineage-flow")).toBeVisible();
    }
    await page.waitForTimeout(400);
    if (COMPARE) {
      await expect(page).toHaveScreenshot(shot.name, {
        maxDiffPixelRatio: 0.02,
        animations: "disabled",
        fullPage: false,
      });
    } else {
      const image = await page.screenshot({
        animations: "disabled",
        ...(SCREENSHOT_DIR ? { path: join(SCREENSHOT_DIR, shot.name) } : {}),
      });
      if (!SCREENSHOT_DIR) {
        await testInfo.attach(shot.name, { body: image, contentType: "image/png" });
      }
      expect(image.byteLength).toBeGreaterThan(1000);
    }
    await testInfo.attach("browser-console.txt", {
      body: consoleMessages.join("\n") || "(no console messages)",
      contentType: "text/plain",
    });
    expect(consoleErrors, consoleMessages.join("\n")).toEqual([]);
  });
}
