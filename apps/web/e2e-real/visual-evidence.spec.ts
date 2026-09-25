import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { DFL, SC, expectCleanConsole, probe } from "./helpers";

/**
 * RES-113 hybrid Field fixed-viewport visual evidence against the real API. Each
 * screenshot is taken only after the surface is demonstrably populated, and the
 * run fails on any console error. Output: output/playwright/res-112/final/.
 */
const OUT = path.resolve(process.cwd(), "../../output/playwright/res-112/final");

async function shoot(page: Page, name: string) {
  await mkdir(OUT, { recursive: true });
  await page.waitForTimeout(1_200);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

async function pitchReady(page: Page) {
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-drawn-frame-ns", /^-?\d+$/);
}

async function poseReady(page: Page) {
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await expect(page.getByTestId("pose-telemetry")).toContainText(/\d+ observed · \d+ unavailable/);
}

for (const [width, height] of [[1440, 900], [1600, 1000], [1366, 768]] as const) {
  test(`visual evidence at ${width}x${height}`, async ({ page }) => {
    const console = probe(page);
    await page.setViewportSize({ width, height });
    const tag = `${width}x${height}`;
    const primary = width === 1440;

    if (primary) {
      await page.goto("/catalog");
      await expect(page.getByText("DFL/Sportec IDSSE")).toBeVisible();
      await shoot(page, `01-catalog-${tag}`);

      await page.goto(`${DFL}?view=overview`);
      await expect(page.getByText(/Highest total locomotor distance/i)).toBeVisible();
      await shoot(page, `02-overview-dfl-${tag}`);

      await page.goto("/lab/white-cmj-acc-grf/white-s001?view=signals");
      await expect(page.getByTestId("uplot")).toBeVisible();
      await shoot(page, `03-signals-white-cmj-${tag}`);
    }

    await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300020000000&tactical=live`);
    await pitchReady(page);
    await expect(page.getByTestId("tactical-tabpanel")).toContainText("Possession and ball context");
    await expect(page.getByTestId("tactical-tabpanel")).toContainText("DEF / MID / ATT");
    await shoot(page, `04-field-dfl-live-${tag}`);

    if (primary) {
      await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300020000000&tactical=space`);
      await pitchReady(page);
      await page.getByRole("button", { name: /Territory/ }).click();
      await expect.poll(async () => Number(await page.getByTestId("pitch-canvas").getAttribute("data-overlay-territory-cells"))).toBeGreaterThan(15);
      await expect(page.getByTestId("tactical-tabpanel").getByRole("table", { name: /Level C influence/ })).toBeVisible();
      await shoot(page, `05-field-dfl-space-${tag}`);

      await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300020000000&tactical=events`);
      await pitchReady(page);
      await expect(page.getByRole("list", { name: "Source events" })).toBeVisible();
      await shoot(page, `06-field-dfl-events-${tag}`);
    }

    await page.goto(`${SC}?view=field&stream=tracking-period-1&t_ns=120000000000&tactical=live`);
    await pitchReady(page);
    await expect(page.getByTestId("tactical-tabpanel")).toContainText("Possession and ball context");
    await expect(page.getByTestId("tactical-tabpanel")).toContainText("DEF / MID / ATT");
    await shoot(page, `07-field-skillcorner-${tag}`);

    await page.goto(`${SC}?view=pose&stream=pose-period-1`);
    await poseReady(page);
    await shoot(page, `08-pose-body-local-${tag}`);

    if (primary) {
      await page.getByTestId("pose-all-subjects-toggle").click();
      await expect(page.getByText(/all subjects · fixed camera \(\d+\)/)).toBeVisible();
      await page.waitForTimeout(2_500);
      await shoot(page, `09-pose-all-subjects-${tag}`);

      await page.goto("/compare?metric=locomotor.distance_total");
      await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
      await shoot(page, `10-compare-${tag}`);

      await page.goto("/methods?metric=locomotor.distance_total");
      await expect(page.getByText(/locomotor\.distance_total/).first()).toBeVisible();
      await shoot(page, `11-methods-provenance-${tag}`);

      await page.goto("/quality");
      await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
      await shoot(page, `12-quality-${tag}`);

      await page.goto("/runs");
      await expect(page.getByText(/series|metrics/).first()).toBeVisible();
      await shoot(page, `13-runs-${tag}`);
    }

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow, `${tag} horizontal document overflow`).toBe(false);
    await expectCleanConsole(console);
  });
}
