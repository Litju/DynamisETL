import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

const VIEWPORTS = [
  { name: "laptop-workstation", width: 1440, height: 900 },
  { name: "large-workstation", width: 1600, height: 1000 },
] as const;

const ROUTES = [
  "/catalog",
  "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=overview&t_ns=50000000",
  "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000",
  "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field",
  "/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0",
  "/compare?metric=pose.angular_rom.left_knee",
  "/methods?metric=pose.angular_rom.left_knee&result=dm-pose-rom",
  "/quality",
  "/runs",
] as const;

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

for (const viewport of VIEWPORTS) {
  for (const route of ROUTES) {
    test(`${viewport.name}: ${route} stays within the workstation viewport`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(route);
      await page.waitForLoadState("networkidle");

      const dimensions = await page.evaluate(() => ({
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        documentHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
      }));
      expect(dimensions.documentWidth, `horizontal overflow on ${route}`).toBeLessThanOrEqual(
        dimensions.viewportWidth + 1,
      );
      expect(dimensions.documentHeight, `vertical document scroll on ${route}`).toBeLessThanOrEqual(
        dimensions.viewportHeight + 1,
      );

      if (route.includes("view=signals") || route.startsWith("/compare") || route.includes("view=overview")) {
        await expect(page.getByTestId("echart").first()).toBeVisible();
        const chart = await page.getByTestId("echart").first().boundingBox();
        expect(chart?.width ?? 0).toBeGreaterThanOrEqual(320);
        expect(chart?.height ?? 0).toBeGreaterThanOrEqual(180);
      }
      if (route.includes("view=field")) {
        await expect(page.getByTestId("pitch-canvas")).toBeVisible();
        const pitch = await page.getByTestId("pitch-canvas").boundingBox();
        expect(pitch?.width ?? 0).toBeGreaterThanOrEqual(480);
        expect(pitch?.height ?? 0).toBeGreaterThanOrEqual(260);
      }
      if (route.includes("view=pose")) {
        await expect(page.getByTestId("pose-canvas")).toBeVisible();
        const pose = await page.getByTestId("pose-canvas").boundingBox();
        expect(pose?.width ?? 0).toBeGreaterThanOrEqual(480);
        expect(pose?.height ?? 0).toBeGreaterThanOrEqual(260);
      }
    });
  }
}
