import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

test("catalog does not download renderer engines before a laboratory opens", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await installApiMocks(page);
  await page.goto("/catalog");
  await page.waitForLoadState("networkidle");

  const catalogRequests = requests.join("\n");
  expect(catalogRequests).not.toMatch(/echarts|pixi\.js|three(?:\.module)?|PoseScene|LineageGraph/i);

  const uPlotRequest = page.waitForRequest(
    (request) => /uplot/i.test(request.url()),
    { timeout: 10_000 },
  );
  await page.goto(
    "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000",
  );
  await expect(page.getByTestId("uplot")).toHaveAttribute("data-renderer-ready", "true");
  expect((await uPlotRequest).url()).toMatch(/uplot/i);
});
