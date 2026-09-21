import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

test("Report Light keeps the shell readable at a large workstation viewport", async ({ page }) => {
  await installApiMocks(page);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/catalog");
  await page.getByRole("button", { name: "Switch to Report Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const dimensions = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: window.innerWidth,
  }));
  expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
  await expect(page.getByRole("heading", { name: "Multimodal human performance data" })).toBeVisible();
});
