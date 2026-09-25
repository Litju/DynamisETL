import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

type RendererCase = {
  readonly name: string;
  readonly route: string;
  readonly host: string;
  readonly renderer: string;
  readonly canvasHost?: string;
};

const CASES: readonly RendererCase[] = [
  {
    name: "uPlot signal trace",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000",
    host: "uplot",
    renderer: "uplot",
  },
  {
    name: "R3F field replay",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field",
    host: "pitch-canvas",
    renderer: "r3f",
    canvasHost: "matchlab-canvas",
  },
  {
    name: "R3F pose viewer",
    route: "/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0",
    host: "pose-canvas",
    renderer: "r3f",
    canvasHost: "matchlab-canvas",
  },
];

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

for (const candidate of CASES) {
  test(`${candidate.name} creates a real browser canvas without console errors`, async ({ page }, testInfo) => {
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
    page.on("response", (response) => {
      if (response.status() >= 400) {
        const entry = `http ${response.status()}: ${response.url()}`;
        consoleMessages.push(entry);
        consoleErrors.push(entry);
      }
    });

    await page.goto(candidate.route);
    const host = page.getByTestId(candidate.host);
    await expect(host).toHaveAttribute("data-renderer", candidate.renderer);
    if (candidate.name === "R3F field replay") {
      await expect(host).toHaveAttribute("data-pitch-length-m", "105");
      await expect(host).toHaveAttribute("data-pitch-width-m", "68");
    }
    await expect(host).toHaveAttribute("data-renderer-ready", "true");
    const canvas = page.getByTestId(candidate.canvasHost ?? candidate.host).locator("canvas").first();
    await expect(canvas).toBeVisible();
    const details = await canvas.evaluate((node) => {
      const element = node as HTMLCanvasElement;
      const context =
        element.getContext("webgl2") ??
        element.getContext("webgl") ??
        element.getContext("2d");
      return {
        width: element.width,
        height: element.height,
        hasContext: context !== null,
        dataUrlBytes: element.toDataURL().length,
      };
    });
    expect(details.width).toBeGreaterThan(0);
    expect(details.height).toBeGreaterThan(0);
    expect(details.hasContext).toBe(true);
    expect(details.dataUrlBytes).toBeGreaterThan(100);
    await testInfo.attach("browser-console.txt", {
      body: consoleMessages.join("\n") || "(no console messages)",
      contentType: "text/plain",
    });
    expect(consoleErrors, consoleMessages.join("\n")).toEqual([]);
  });
}

test("keeps one MatchLab Canvas mounted across Field and Pose modes", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0");
  const canvas = page.getByTestId("matchlab-canvas").locator("canvas");
  await expect(canvas).toHaveCount(1);
  const originalCanvas = await canvas.elementHandle();
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");

  await page.getByRole("tab", { name: "field", exact: true }).click();
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await expect(page.getByTestId("matchlab-canvas").locator("canvas")).toHaveCount(1);
  expect(await originalCanvas?.evaluate((element) => element.isConnected)).toBe(true);
  await page.getByRole("tab", { name: "pose", exact: true }).click();
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
  const currentCanvas = await page.getByTestId("matchlab-canvas").locator("canvas").elementHandle();
  expect(await currentCanvas?.evaluate((element, original) => element === original, originalCanvas)).toBe(true);
});

test("keeps Pixi reachable only through the development parity oracle", async ({ page }) => {
  await page.addInitScript(() => window.localStorage.setItem("dynamis-matchlab-pixi-parity", "1"));
  await page.goto("/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field");
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer", "pixi");
  await expect(page.getByTestId("pitch-canvas").locator("canvas")).toBeVisible();
});
