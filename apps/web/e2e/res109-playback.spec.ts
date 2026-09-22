import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

function uniqueBounds(urls: readonly string[]): Array<[number, number]> {
  const pairs = new Map<string, [number, number]>();
  for (const raw of urls) {
    const url = new URL(raw);
    if (url.searchParams.get("format") === "arrow") continue;
    const from = url.searchParams.get("from_ns");
    const to = url.searchParams.get("to_ns");
    if (from !== null && to !== null) pairs.set(`${from}..${to}`, [Number(from), Number(to)]);
  }
  return [...pairs.values()].sort((left, right) => left[0] - right[0]);
}

function playheadNs(page: import("@playwright/test").Page): Promise<bigint> {
  return page.getByTestId("playhead-ns").textContent().then((text) => {
    const match = text?.match(/-?\d+/);
    if (!match) throw new Error(`missing playhead value: ${text}`);
    return BigInt(match[0]);
  });
}

function expectContiguous(bounds: readonly [number, number][]): void {
  expect(bounds.length).toBeGreaterThanOrEqual(3);
  for (let index = 1; index < bounds.length; index += 1) {
    expect(bounds[index]![0]).toBe(bounds[index - 1]![1] + 1);
  }
}

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test("RES-109 Pose crosses multiple exact chunks and keeps telemetry on the live frame", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/artifacts/pose-sample/window")) requests.push(request.url());
  });
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=0");
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  const telemetry = page.getByTestId("pose-telemetry");
  await expect(telemetry).toBeVisible();
  const before = await playheadNs(page);
  await page.getByLabel("Playback rate").selectOption("4");
  await page.getByRole("button", { name: "Play" }).click();
  await page.waitForTimeout(5_000);
  const during = await playheadNs(page);
  const pause = page.getByRole("button", { name: "Pause" });
  if (await pause.count()) await pause.click();
  expect(during).toBeGreaterThan(before + 10_000_000_000n);
  expectContiguous(uniqueBounds(requests));
  expect(requests.filter((url) => new URL(url).searchParams.get("entity_id") === "SC-P1").length).toBeGreaterThan(0);
});

test("RES-109 Field crosses forward and reverse chunk boundaries without scope drift", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/artifacts/tracking-sample/window")) requests.push(request.url());
  });
  await page.goto("/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field&t_ns=0");
  await expect(page.getByTestId("pitch-canvas")).toBeVisible();
  await page.getByLabel("Playback rate").selectOption("4");
  await page.getByRole("button", { name: "Play" }).click();
  await page.waitForTimeout(5_000);
  const forward = await playheadNs(page);
  const pause = page.getByRole("button", { name: "Pause" });
  if (await pause.count()) await pause.click();
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  await page.getByRole("button", { name: "Reverse" }).click();
  await expect(page.getByTestId("playback-direction")).toHaveAttribute("data-direction", "reverse");
  await page.waitForTimeout(1_800);
  const reverse = await playheadNs(page);
  await page.getByRole("button", { name: "Pause" }).click();
  expect(forward).toBeGreaterThan(10_000_000_000n);
  expect(reverse).toBeLessThan(forward);
  expectContiguous(uniqueBounds(requests));
  expect(requests.every((url) => !new URL(url).searchParams.has("entity_id"))).toBe(true);
});

test("RES-109 delayed exact handoff is explicit BUFFERING and resumes", async ({ page }) => {
  let delayedFromNs: number | null = null;
  let releaseNext: (() => void) | null = null;
  const releaseGate = new Promise<void>((resolve) => {
    releaseNext = resolve;
  });
  await page.route("**/api/artifacts/pose-sample/window**", async (route) => {
    const url = new URL(route.request().url());
    const fromNs = Number(url.searchParams.get("from_ns") ?? "0");
    if (fromNs > 0 && delayedFromNs === null) {
      delayedFromNs = fromNs;
      await releaseGate;
      await new Promise((resolve) => setTimeout(resolve, 3_000));
    }
    await route.fallback();
  });
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=0");
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  await page.getByLabel("Playback rate").selectOption("4");
  await page.getByRole("button", { name: "Play" }).click();
  releaseNext?.();
  await expect(page.getByTestId("playback-buffering").first()).toBeVisible({ timeout: 2_500 });
  await expect(page.getByTestId("playback-buffering").first()).toBeHidden({ timeout: 8_000 });
  await page.getByRole("button", { name: "Pause" }).click();
});

test("RES-109 Pose seek exposes coordinate and camera ownership modes", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=16000000000");
  await expect(page.getByText(/local analytical frame · Z is player-centroid-relative/)).toBeVisible();
  await page.getByTestId("pose-match-world-mode").click();
  await expect(page.getByText(/match\/world frame · source XY placement preserved/)).toBeVisible();
  await page.getByRole("button", { name: "follow-subject" }).click();
  await expect(page.getByRole("button", { name: "follow-subject" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "joint-focus" }).click();
  await page.getByRole("button", { name: "manual" }).click();
  await expect(page.getByRole("button", { name: "manual" })).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("pose-camera-reset").click();
  await expect(page.getByTestId("pose-body-local-mode")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "body-local" }).nth(1)).toHaveAttribute("aria-pressed", "true");
});

test("RES-109 §12 paused subject switch rewinds to the first exact observation", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=16000000000");
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  await page.locator("#pose-subject").selectOption("SC-P2");
  await expect(page).toHaveURL(/subject=SC-P2/);
  await expect(page).toHaveURL(/t_ns=12000000000/);
  await expect(page.getByTestId("pose-telemetry").getByText("29 observed · 0 unavailable")).toBeVisible();
});

test("RES-109 §12 playing subject switch stops playback without stale subject data", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=12000000000");
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  await page.getByLabel("Playback rate").selectOption("4");
  await page.getByRole("button", { name: "Play" }).click();
  await page.waitForTimeout(500);
  await page.locator("#pose-subject").selectOption("SC-P2");
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  await expect(page).toHaveURL(/subject=SC-P2/);
  await expect(page).toHaveURL(/t_ns=12000000000/);
  await expect(page.getByTestId("pose-telemetry").getByText("29 observed · 0 unavailable")).toBeVisible();
});

test("RES-109 §12 buffering subject switch retires only the previous subject", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/artifacts/pose-sample/window")) requests.push(request.url());
  });
  await page.route("**/api/artifacts/pose-sample/window**", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("entity_id") === "SC-P1" && Number(url.searchParams.get("from_ns") ?? "0") > 0) {
      await new Promise((resolve) => setTimeout(resolve, 2_000));
    }
    await route.fallback();
  });
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=0");
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  await page.getByLabel("Playback rate").selectOption("4");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByTestId("playback-buffering").first()).toBeVisible({ timeout: 2_500 });
  await page.locator("#pose-subject").selectOption("SC-P2");
  await expect(page).toHaveURL(/subject=SC-P2/);
  await expect(page).toHaveURL(/t_ns=12000000000/);
  await expect(page.getByTestId("pose-telemetry").getByText("29 observed · 0 unavailable")).toBeVisible({ timeout: 5_000 });
  expect(requests.some((url) => new URL(url).searchParams.get("entity_id") === "SC-P2")).toBe(true);
});

test("RES-109 §12 distinguishes temporary absence and no Pose for numeric ids", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P2&view=pose&t_ns=8000000000");
  await expect(page.getByText("Subject SC-P2 is not observed at 00:00:08.000.")).toBeVisible();
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=560986&view=pose&t_ns=8000000000");
  await expect(page.getByTestId("workbench").getByText("No Pose observations for subject 560986 in period-1.")).toBeVisible();
  await expect(page.getByTestId("pose-telemetry-status")).toContainText("No Pose observations");
  await expect(page.getByText("all landmarks unavailable")).toHaveCount(0);
});

test("RES-109 §12 all-subject focus keeps the global exact query unscoped", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/artifacts/pose-sample/window")) requests.push(request.url());
  });
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=12000000000");
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  await page.getByTestId("pose-all-subjects-toggle").click();
  await page.locator("#pose-subject").selectOption("SC-P2");
  await expect(page).toHaveURL(/subject=SC-P2/);
  await expect(page.getByTestId("pose-all-subjects-toggle")).toHaveText("all subjects · fixed camera");
  expect(requests.some((url) => !new URL(url).searchParams.has("entity_id"))).toBe(true);
});

test("RES-109 §12 subject navigation is stable across reload and history", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=16000000000");
  await page.locator("#pose-subject").selectOption("SC-P2");
  await expect(page).toHaveURL(/subject=SC-P2.*t_ns=12000000000/);
  await page.reload();
  await expect(page).toHaveURL(/subject=SC-P2.*t_ns=12000000000/);
  await page.goBack();
  await expect(page).toHaveURL(/subject=SC-P1/);
  await page.goForward();
  await expect(page).toHaveURL(/subject=SC-P2.*t_ns=12000000000/);
});
