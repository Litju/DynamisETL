import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

const ROUTES = [
  "/catalog",
  "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=overview&t_ns=50000000",
  "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field",
  "/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0",
  "/methods?metric=pose.angular_rom.left_knee",
  "/runs",
  "/quality",
  "/compare?metric=pose.angular_rom.left_knee",
];

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

for (const route of ROUTES) {
  test(`axe: no serious or critical violations on ${route}`, async ({ page }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    const serious = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
    const summary = serious.map((violation) => ({
      id: violation.id,
      help: violation.help,
      targets: violation.nodes.map((node) => node.target),
    }));
    expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
  });
}
