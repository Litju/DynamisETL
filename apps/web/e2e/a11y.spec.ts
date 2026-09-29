import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

/** Every archetype's primary route: Research, Data, entity context, World entry, workbench, Library. */
const ROUTES = [
  "/",
  "/data",
  "/data?domain=human",
  "/data/edition/skillcorner:edition:870",
  "/performance?dataset=white-cmj-acc-grf&session=cmj-1",
  "/lab",
  "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=overview&t_ns=50000000",
  "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field",
  "/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0",
  "/library",
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

test("reduced motion: the shell and palette work with animations removed", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const trigger = page.getByRole("button", { name: /^Search/ });
  await trigger.click();
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  const duration = await page.evaluate(() => getComputedStyle(document.querySelector(".d-pop")!).transitionDuration);
  expect(duration.split(",").every((value) => Number.parseFloat(value) < 0.01)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  // Focus returns to the control that opened the overlay.
  await expect(trigger).toBeFocused();
});
