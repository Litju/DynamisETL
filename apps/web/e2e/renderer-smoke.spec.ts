import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

type RendererCase = {
  readonly name: string;
  readonly route: string;
  readonly host: string;
  readonly renderer: string;
};

const CASES: readonly RendererCase[] = [
  {
    name: "ECharts signal trace",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000",
    host: "echart",
    renderer: "echarts",
  },
  {
    name: "Pixi field replay",
    route: "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field",
    host: "pitch-canvas",
    renderer: "pixi",
  },
  {
    name: "R3F pose viewer",
    route: "/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0",
    host: "pose-canvas",
    renderer: "r3f",
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

    await page.goto(candidate.route);
    const host = page.getByTestId(candidate.host);
    await expect(host).toHaveAttribute("data-renderer", candidate.renderer);
    await expect(host).toHaveAttribute("data-renderer-ready", "true");
    const canvas = host.locator("canvas").first();
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
