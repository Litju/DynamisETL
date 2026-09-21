import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

/**
 * Visual regression for presentation drift (never scientific validation).
 *
 * Comparing rendered pixels across platforms is noisy, so comparisons only run
 * when `VISUAL_REGRESSION=1` is set on a reference platform; the default CI run
 * captures the artifacts as attachments instead. Baselines live next to this
 * spec (`*.spec.ts-snapshots/`) and are refreshed with
 * `VISUAL_REGRESSION=1 pnpm test:e2e --update-snapshots`.
 */
const COMPARE = process.env.VISUAL_REGRESSION === "1";

const SHOTS: Array<{ name: string; route: string; clip?: { width: number; height: number } }> = [
  { name: "shell-catalog.png", route: "/catalog" },
  {
    name: "inspector-method.png",
    route: "/lab/skillcorner-opendata/1925299?view=overview&t_ns=50000000",
  },
  {
    name: "signal-lab.png",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000",
  },
  {
    name: "pitch-lab.png",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field",
  },
  {
    name: "pose-lab.png",
    route: "/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0",
  },
  {
    name: "provenance-lineage.png",
    route: "/methods?metric=pose.angular_rom.left_knee&result=dm-pose-rom",
  },
];

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

for (const shot of SHOTS) {
  test(`visual: ${shot.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(shot.route);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(400);
    if (COMPARE) {
      await expect(page).toHaveScreenshot(shot.name, {
        maxDiffPixelRatio: 0.02,
        animations: "disabled",
        fullPage: false,
      });
    } else {
      const image = await page.screenshot({ animations: "disabled" });
      await testInfo.attach(shot.name, { body: image, contentType: "image/png" });
      expect(image.byteLength).toBeGreaterThan(1000);
    }
  });
}
