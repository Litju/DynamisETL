import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

/**
 * RES-112 audit capture. Opt-in (RES112_AUDIT_PHASE=before|after): it records
 * fixed-viewport screenshots, console output, failed requests and API request
 * counts for every workbench surface against the real local API. Findings are
 * transcribed into docs/audits/field-pose-system/; this spec only gathers
 * evidence and asserts nothing about product correctness.
 */
const phase = process.env.RES112_AUDIT_PHASE;
const OUT = path.resolve(process.cwd(), "../../output/playwright/res-112", phase ?? "unset");

const DFL = "/lab/dfl-sportec-idsse/DFL-MAT-J03WPY";
const SC = "/lab/skillcorner-opendata/1925299";

interface Probe {
  console: string[];
  pageErrors: string[];
  failed: string[];
  api: string[];
}

function attach(page: Page): Probe {
  const probe: Probe = { console: [], pageErrors: [], failed: [], api: [] };
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      probe.console.push(`${message.type()}: ${message.text().slice(0, 400)}`);
    }
  });
  page.on("pageerror", (error) => probe.pageErrors.push(error.message.slice(0, 400)));
  page.on("requestfailed", (request) => probe.failed.push(`${request.failure()?.errorText} ${request.url()}`));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api/")) probe.api.push(`${response.status()} ${url.pathname}${url.search}`);
  });
  return probe;
}

const records: Record<string, unknown> = {};

async function shot(page: Page, name: string, probe: Probe, extra: Record<string, unknown> = {}) {
  await mkdir(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
  records[name] = {
    url: page.url(),
    console: [...probe.console],
    pageErrors: [...probe.pageErrors],
    failed: [...probe.failed],
    apiRequests: probe.api.length,
    apiSample: probe.api.slice(-40),
    ...extra,
  };
  probe.console.length = 0;
  probe.pageErrors.length = 0;
  probe.failed.length = 0;
  probe.api.length = 0;
}

async function settle(page: Page, ms = 2_500) {
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => undefined);
  await page.waitForTimeout(ms);
}

async function text(page: Page, selector: string) {
  const locator = page.locator(selector).first();
  return (await locator.count()) ? (await locator.innerText()).slice(0, 1500) : null;
}

async function scrollOverflow(page: Page) {
  return page.evaluate(() => ({
    docScrollWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
  }));
}

test.skip(!phase, "Set RES112_AUDIT_PHASE=before|after to capture audit evidence.");

test.afterAll(async () => {
  await mkdir(OUT, { recursive: true });
  const target = path.join(OUT, "audit-log.json");
  // A failed test restarts its worker, so merge into the evidence already written.
  const previous = await readFile(target, "utf8").then((body) => JSON.parse(body) as Record<string, unknown>).catch(() => ({}));
  await writeFile(target, JSON.stringify({ ...previous, ...records }, null, 2) + "\n");
});

test("system routes", async ({ page }) => {
  const probe = attach(page);
  for (const [name, url] of [
    ["01-catalog", "/catalog"],
    ["02-overview-dfl", `${DFL}?view=overview`],
    ["03-signals-dfl", `${DFL}?view=signals`],
    ["10-compare", "/compare"],
    ["11-methods", "/methods"],
    ["12-quality", "/quality"],
    ["13-runs", "/runs"],
  ] as const) {
    await page.goto(url);
    await settle(page);
    await shot(page, name, probe, { overflow: await scrollOverflow(page), main: await text(page, "main") });
  }
});

test("DFL field and tactical pane", async ({ page }) => {
  const probe = attach(page);
  await page.goto(`${DFL}?view=field`);
  await settle(page, 4_000);
  await shot(page, "04-field-dfl-live", probe, {
    pane: await text(page, "[aria-label='Tactical analysis views'] >> xpath=ancestor::section[1]"),
    layers: await text(page, "[aria-label='Scene layers']"),
  });
  for (const tab of ["Space", "Shape", "Range", "Events", "Report"]) {
    const control = page.getByRole("tab", { name: tab, exact: true });
    if (await control.count()) {
      await control.click();
      await settle(page, 1_500);
    }
    await shot(page, `05-field-dfl-${tab.toLowerCase()}`, probe, {
      pane: await text(page, "[aria-label='Tactical analysis views'] >> xpath=ancestor::section[1]"),
    });
  }
  await page.getByRole("tab", { name: "Live", exact: true }).click().catch(() => undefined);
  const play = page.getByRole("button", { name: "Play" });
  await play.click();
  await page.waitForTimeout(4_000);
  await page.getByRole("button", { name: "Pause playback" }).click().catch(() => undefined);
  await settle(page, 1_000);
  await shot(page, "06-field-dfl-after-play", probe, {
    playhead: await text(page, "[data-testid='playhead-ns']"),
  });
});

test("SkillCorner field, overlays and playback", async ({ page }) => {
  const probe = attach(page);
  await page.goto(`${SC}?view=field`);
  await settle(page, 4_000);
  await shot(page, "07-field-sc-default", probe, {
    layers: await text(page, "[aria-label='Scene layers']"),
    pane: await text(page, "[aria-label='Tactical analysis views'] >> xpath=ancestor::section[1]"),
  });
  for (const layer of ["Hull", "Territory", "Influence"]) {
    const name = layer === "Influence" ? /Influence.*model/i : layer;
    const toggle = page.getByRole("button", { name });
    await expect(toggle).toBeVisible();
    await toggle.click();
    await settle(page, 2_000);
    await shot(page, `07-field-sc-layer-${layer.toLowerCase()}`, probe, {
      pressed: await toggle.getAttribute("aria-pressed"),
    });
  }
  const pixiMarker = await page.evaluate(() => document.querySelectorAll("[data-testid='pitch-canvas'] canvas").length);
  const before = probe.api.length;
  const perf = await page.evaluate(() => {
    const counts = { frames: 0, canvases: new Set<HTMLCanvasElement>() };
    const tick = () => {
      counts.frames += 1;
      document.querySelectorAll<HTMLCanvasElement>("[data-testid='pitch-canvas'] canvas").forEach((canvas) => counts.canvases.add(canvas));
      if (counts.frames < 10_000) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    (window as unknown as { __res112?: typeof counts }).__res112 = counts;
    return true;
  });
  expect(perf).toBe(true);
  await page.getByRole("button", { name: "Play" }).click();
  await page.waitForTimeout(5_000);
  const during = await page.evaluate(() => {
    const counts = (window as unknown as { __res112?: { frames: number; canvases: Set<HTMLCanvasElement> } }).__res112;
    return { rafFrames: counts?.frames ?? 0, distinctCanvasesSeen: counts?.canvases.size ?? 0 };
  });
  await page.getByRole("button", { name: "Pause playback" }).click().catch(() => undefined);
  await settle(page, 1_000);
  await shot(page, "07-field-sc-after-play", probe, {
    canvasesBeforePlay: pixiMarker,
    during,
    apiRequestsDuringPlay: probe.api.length - before,
  });
  for (const tab of ["Space", "Shape", "Range", "Events", "Report"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await settle(page, 1_500);
    await shot(page, `08-field-sc-${tab.toLowerCase()}`, probe, {
      pane: await text(page, "[aria-label='Tactical analysis views'] >> xpath=ancestor::section[1]"),
    });
  }
});

test("SkillCorner pose", async ({ page }) => {
  const probe = attach(page);
  await page.goto(`${SC}?view=pose`);
  await settle(page, 5_000);
  await shot(page, "09-pose-default", probe, {
    telemetry: await text(page, "[data-testid='pose-telemetry']"),
    url: page.url(),
  });
  const subject = page.locator("#pose-subject");
  const options = await subject.locator("option").allInnerTexts().catch(() => []);
  const values = await subject.locator("option").evaluateAll((items) => items.map((item) => (item as HTMLOptionElement).value)).catch(() => []);
  if (values.length > 2) {
    await subject.selectOption(values[2]!);
    await settle(page, 3_000);
    await shot(page, "09-pose-subject-switch", probe, {
      options: options.slice(0, 40),
      telemetry: await text(page, "[data-testid='pose-telemetry']"),
    });
  }
  await page.getByRole("button", { name: "Play" }).click();
  await page.waitForTimeout(4_000);
  await shot(page, "09-pose-playing", probe, { telemetry: await text(page, "[data-testid='pose-telemetry']") });
  if (values.length > 3) {
    await subject.selectOption(values[3]!);
    await page.waitForTimeout(3_000);
    await shot(page, "09-pose-switch-while-playing", probe, { telemetry: await text(page, "[data-testid='pose-telemetry']") });
  }
  await page.getByRole("button", { name: "Pause playback" }).click().catch(() => undefined);
  const world = page.getByTestId("pose-match-world-mode");
  if (await world.count()) {
    await world.click();
    await settle(page, 2_500);
    await shot(page, "09-pose-world", probe);
  }
  const all = page.getByTestId("pose-all-subjects-toggle");
  if (await all.count()) {
    await all.click();
    await settle(page, 4_000);
    await shot(page, "09-pose-all-subjects", probe, { telemetry: await text(page, "[data-testid='pose-telemetry']") });
  }
});

test("workstation widths", async ({ page }) => {
  const probe = attach(page);
  for (const [width, height] of [[1600, 1000], [1366, 768]] as const) {
    await page.setViewportSize({ width, height });
    for (const [name, url] of [
      ["field-dfl", `${DFL}?view=field`],
      ["field-sc", `${SC}?view=field`],
      ["pose-sc", `${SC}?view=pose`],
    ] as const) {
      await page.goto(url);
      await settle(page, 4_000);
      await shot(page, `14-${width}x${height}-${name}`, probe, { overflow: await scrollOverflow(page) });
    }
  }
});
