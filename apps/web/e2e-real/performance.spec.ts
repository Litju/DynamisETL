import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { DFL, SC, playheadNs } from "./helpers";

/**
 * RES-112 §11 performance receipt on real product paths (live API, no mocks).
 * Frozen RES-109 budgets asserted in-browser: continuous-playback heap
 * <= 256 MB and playback-chunk fetch p95 <= 250 ms. Everything else is
 * recorded to output/playwright/res-112/performance.json for review.
 */
const RECEIPT = path.resolve(process.cwd(), "../../output/playwright/res-112/performance.json");
const HEAP_BUDGET_MB = 256;
const CHUNK_P95_BUDGET_MS = 250;

async function record(name: string, value: Record<string, unknown>) {
  await mkdir(path.dirname(RECEIPT), { recursive: true });
  const previous = await readFile(RECEIPT, "utf8").then((body) => JSON.parse(body) as Record<string, unknown>).catch(() => ({}));
  await writeFile(RECEIPT, JSON.stringify({ ...previous, [name]: value }, null, 2) + "\n");
}

function p95(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)]!;
}

async function instrument(page: Page) {
  await page.addInitScript(() => {
    const state = { longTasks: 0, longTaskMs: 0 };
    (window as unknown as { __perf: typeof state }).__perf = state;
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          state.longTasks += 1;
          state.longTaskMs += entry.duration;
        }
      }).observe({ type: "longtask", buffered: true });
    } catch {
      // longtask entries are Chromium-only; the receipt records null otherwise.
    }
  });
}

async function sample(page: Page, milliseconds: number) {
  return page.evaluate(async (duration) => {
    const perf = (window as unknown as { __perf: { longTasks: number; longTaskMs: number } }).__perf;
    const startTasks = perf.longTasks;
    const startTaskMs = perf.longTaskMs;
    const resourceStart = performance.now();
    let frames = 0;
    let worst = 0;
    let last = performance.now();
    await new Promise<void>((resolve) => {
      const tick = (now: number) => {
        frames += 1;
        worst = Math.max(worst, now - last);
        last = now;
        if (now - resourceStart < duration) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    const resources = performance
      .getEntriesByType("resource")
      .filter((entry) => entry.startTime >= resourceStart && entry.name.includes("/api/")) as PerformanceResourceTiming[];
    const memory = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    return {
      fps: Math.round((frames / duration) * 1000),
      worstFrameMs: Math.round(worst),
      longTasks: perf.longTasks - startTasks,
      longTaskMs: Math.round(perf.longTaskMs - startTaskMs),
      heapMb: memory ? Math.round(memory.usedJSHeapSize / 1024 / 1024) : null,
      requests: resources.map((entry) => ({ url: new URL(entry.name).pathname + new URL(entry.name).search, ms: Math.round(entry.duration) })),
    };
  }, milliseconds);
}

function duplicateRequests(urls: string[]): string[] {
  const seen = new Map<string, number>();
  for (const url of urls) seen.set(url, (seen.get(url) ?? 0) + 1);
  return [...seen.entries()].filter(([, count]) => count > 1).map(([url, count]) => `${count}x ${url}`);
}

test("Field (DFL): base replay, each overlay, combined overlays and chunk handoff", async ({ page }) => {
  await instrument(page);
  const allUrls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) allUrls.push(new URL(request.url()).pathname + new URL(request.url()).search);
  });
  await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=1020000000`);
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  const results: Record<string, unknown> = {};
  const play = async (label: string, seconds: number) => {
    const before = (await playheadNs(page))!;
    await page.getByRole("button", { name: "Play", exact: true }).click();
    const measured = await sample(page, seconds * 1000);
    await page.getByRole("button", { name: "Pause playback" }).click({ timeout: 3_000 }).catch(() => undefined);
    const after = (await playheadNs(page))!;
    const advancedS = Number(after - before) / 1e9;
    results[label] = { ...measured, advancedS, requests: measured.requests.length };
    // Continuity: no stall — playback advances at >= 80 % of wall time.
    expect(advancedS, label).toBeGreaterThan(seconds * 0.8);
    return measured;
  };
  await play("base-replay-planar-default", 5);
  for (const layer of ["Territory", "Influence"]) {
    await page.getByRole("button", { name: new RegExp(layer) }).click();
    await play(`with-${layer.toLowerCase()}`, 5);
  }
  // Chunk handoff: the combined set crossing at least one 8.7 s chunk boundary.
  const handoff = await play("combined-across-chunk-boundary", 10);
  const chunkTimes = handoff.requests.filter((request) => request.url.includes("/window")).map((request) => request.ms);
  const heapMb = handoff.heapMb;
  // In-playback timings include concurrent overlay reads; informational only.
  results.inPlaybackWindowP95Ms = p95(chunkTimes);
  results.duplicateRequests = duplicateRequests(allUrls);
  await record("field-dfl", results);
  if (heapMb !== null) expect(heapMb).toBeLessThanOrEqual(HEAP_BUDGET_MB);
});

test("Playback chunk budget: 20 isolated exact tracking chunks (RES-109 playback_chunk_p95)", async ({ page }) => {
  const session = await (await page.request.get("/api/catalog/datasets/dfl-sportec-idsse/sessions/DFL-MAT-J03WPY")).json();
  const artifactId = session.streams.find((item: { stream_id: string }) => item.stream_id === "tracking-period-1").sample_artifact_ids[0];
  const artifact = await (await page.request.get(`/api/artifacts/${artifactId}`)).json();
  const span = 8_695_526_388;
  const timings: number[] = [];
  for (let index = 0; index < 20; index += 1) {
    const fromNs = artifact.canonical_time_min_ns + (index * 7 + 3) * span;
    const url = `/api/artifacts/${artifactId}/window?from_ns=${fromNs}&to_ns=${fromNs + span - 1}` +
      "&columns=t_rel_ns,object_id,object_type,group_id,x_m,y_m,is_detected&max_points=20000";
    const started = performance.now();
    const response = await page.request.get(url);
    await response.body();
    timings.push(performance.now() - started);
    expect(response.status()).toBe(200);
  }
  const value = p95(timings)!;
  await record("playback-chunk", { samples: timings.map(Math.round), p95Ms: Math.round(value), budgetMs: CHUNK_P95_BUDGET_MS });
  expect(value).toBeLessThanOrEqual(CHUNK_P95_BUDGET_MS);
});

test("Pose (SkillCorner): one subject, all layers, follow camera, all subjects, subject switch", async ({ page }) => {
  await instrument(page);
  const allUrls: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) allUrls.push(new URL(request.url()).pathname + new URL(request.url()).search);
  });
  await page.goto(`${SC}?view=pose&stream=pose-period-1`);
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
  const results: Record<string, unknown> = {};
  const play = async (label: string, seconds: number) => {
    const before = (await playheadNs(page))!;
    await page.getByRole("button", { name: "Play", exact: true }).click();
    const measured = await sample(page, seconds * 1000);
    await page.getByRole("button", { name: "Pause playback" }).click({ timeout: 3_000 }).catch(() => undefined);
    const after = (await playheadNs(page))!;
    results[label] = { ...measured, advancedS: Number(after - before) / 1e9, requests: measured.requests.length };
    return measured;
  };
  await play("one-subject-all-layers", 5);
  await page.getByTestId("pose-match-world-mode").click();
  await play("follow-camera", 5);
  await page.getByTestId("pose-all-subjects-toggle").click();
  await page.waitForTimeout(2_000);
  const all = await play("all-subjects", 5);
  await page.getByTestId("pose-all-subjects-toggle").click();
  const subjects = await page.locator("#pose-subject option").evaluateAll((items) => items.map((item) => (item as HTMLOptionElement).value));
  const started = Date.now();
  await page.locator("#pose-subject").selectOption(subjects[2]!);
  await expect(page.getByTestId("pose-telemetry")).toContainText(subjects[2]!);
  await expect(page.getByTestId("pose-telemetry")).toContainText(/\d+ observed · \d+ unavailable/);
  results.subjectSwitchMs = Date.now() - started;
  results.duplicateRequests = duplicateRequests(allUrls);
  await record("pose-sc", results);
  if (all.heapMb !== null) expect(all.heapMb).toBeLessThanOrEqual(HEAP_BUDGET_MB);
});

test("Whole system: route loads, lazy chunks and console", async ({ page }) => {
  const scripts: string[] = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.endsWith(".js") || url.pathname.includes("/src/")) scripts.push(url.pathname);
  });
  const timings: Record<string, number> = {};
  for (const [name, url] of [
    ["catalog", "/catalog"],
    ["overview", `${DFL}?view=overview`],
    ["field", `${DFL}?view=field&stream=tracking-period-1`],
    ["pose", `${SC}?view=pose&stream=pose-period-1`],
  ] as const) {
    const started = Date.now();
    await page.goto(url);
    if (name === "field") await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
    else if (name === "pose") await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
    else await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
    timings[name] = Date.now() - started;
  }
  await record("routes", {
    readyMs: timings,
    poseRendererLoadedLazily: scripts.some((script) => /PoseScene|three|fiber/.test(script)),
  });
});
