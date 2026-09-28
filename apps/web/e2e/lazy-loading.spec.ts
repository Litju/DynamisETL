import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

test("Research, Data and Library do not download renderer engines before a World opens", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await installApiMocks(page);
  for (const route of ["/", "/data", "/data/edition/skillcorner:edition:870", "/library"]) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
  }
  // Metadata only: no dense window, series or frame request from browsing.
  expect(requests.filter((url) => /\/api\/artifacts\/[^/]+\/window|\/tactical\/series\/|\/basketball\/contests\/[^/]+\/frames|\/games\/[^/]+\/plays/.test(url))).toEqual([]);

  const catalogRequests = requests.join("\n");
  expect(catalogRequests).not.toMatch(/echarts|pixi\.js|three(?:\.module)?|PoseScene|LineageGraph/i);

  const uPlotRequest = page.waitForRequest(
    (request) => /uplot/i.test(request.url()),
    { timeout: 30_000 },
  );
  await page.goto(
    "/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000",
  );
  await expect(page.getByTestId("uplot")).toHaveAttribute("data-renderer-ready", "true");
  expect((await uPlotRequest).url()).toMatch(/uplot/i);
});
