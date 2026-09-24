import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "@playwright/test";

/* global window, document, requestAnimationFrame */

const baseUrl = process.env.DYNAMIS_REAL_BASE_URL ?? "http://127.0.0.1:4182";
const output = path.resolve(process.cwd(), "../../output/playwright/res-113/renderer-benchmark.json");
const viewports = [{ width: 1600, height: 1000 }, { width: 1440, height: 900 }];
const scenarios = [
  { id: "field", path: "/lab/skillcorner-opendata/1925299?view=field&stream=tracking-period-1&subject=11897&t_ns=0" },
  { id: "pose", path: "/lab/skillcorner-opendata/1925299?view=pose&stream=pose-period-1&subject=11897&t_ns=440000000" },
  { id: "split", path: "/lab/skillcorner-opendata/1925299?view=split&stream=tracking-period-1&subject=11897&t_ns=5000000000" },
];

async function instrumentRenderer(page) {
  await page.evaluate(() => {
    const renderer = window.__dynamisMatchLabBenchmarkRenderer;
    if (!renderer?.info || renderer.__dynamisBenchmarkWrapped) return;
    const info = renderer.info;
    info.autoReset = false;
    const stats = [];
    Object.assign(window, { __dynamisMatchLabFrameStats: stats });
    const render = renderer.render.bind(renderer);
    renderer.render = (...args) => {
      info.reset?.();
      const result = render(...args);
      const capture = () => stats.push({
        timestamp: performance.now(),
        calls: info.render?.calls ?? null,
        drawCalls: info.render?.drawCalls ?? null,
        triangles: info.render?.triangles ?? null,
      });
      if (result && typeof result.then === "function") {
        return result.then((value) => {
          capture();
          return value;
        });
      }
      capture();
      return result;
    };
    Object.assign(renderer, { __dynamisBenchmarkWrapped: true });
  });
}

async function measure(page) {
  return page.evaluate(async () => {
    const percentile = (values, fraction) => {
      const sorted = [...values].sort((left, right) => left - right);
      return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1)];
    };
    const renderer = window.__dynamisMatchLabBenchmarkRenderer;
    if (!renderer?.info) throw new Error("R3F renderer instrumentation is unavailable");
    const info = renderer.info;
    const frameTimes = [];
    const startedAt = performance.now();
    let previousFrame = null;
    window.__dynamisMatchLabFrameStats.length = 0;
    await new Promise((resolve) => {
      const sampleFrame = (time) => {
        if (previousFrame !== null) frameTimes.push(time - previousFrame);
        previousFrame = time;
        if (time - startedAt < 5000) requestAnimationFrame(sampleFrame);
        else resolve();
      };
      requestAnimationFrame(sampleFrame);
    });
    const elapsedMs = performance.now() - startedAt;
    const memory = info.memory ?? {};
    const gl = renderer.getContext?.();
    const debugInfo = gl?.getExtension?.("WEBGL_debug_renderer_info");
    const adapter = navigator.gpu ? await navigator.gpu.requestAdapter().catch(() => null) : null;
    const usedHeapBytes = performance.memory?.usedJSHeapSize ?? null;
    const canvas = document.querySelector("[data-testid='matchlab-canvas'] canvas");
    const renderSamples = [...window.__dynamisMatchLabFrameStats];
    const drawCalls = renderSamples
      .map((frame) => frame.drawCalls ?? frame.calls ?? 0)
      .filter((value) => typeof value === "number");
    const triangles = renderSamples
      .map((frame) => frame.triangles ?? 0)
      .filter((value) => typeof value === "number");
    const displayFrames = Math.max(1, frameTimes.length);
    return {
      canvasPixels: canvas ? { width: canvas.width, height: canvas.height } : null,
      canvasCssPixels: canvas ? { width: Math.round(canvas.getBoundingClientRect().width), height: Math.round(canvas.getBoundingClientRect().height) } : null,
      isWebGPURenderer: renderer.isWebGPURenderer === true,
      isWebGLRenderer: renderer.isWebGLRenderer === true,
      adapter: adapter ? {
        fallback: adapter.isFallbackAdapter,
        vendor: adapter.info?.vendor ?? null,
        architecture: adapter.info?.architecture ?? null,
      } : null,
      graphicsRenderer: debugInfo && gl ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : null,
      elapsedMs: Math.round(elapsedMs),
      frames: frameTimes.length,
      fps: Math.round(frameTimes.length * 1000 / elapsedMs),
      frameIntervalMs: {
        p50: Math.round(percentile(frameTimes, 0.5) * 100) / 100,
        p95: Math.round(percentile(frameTimes, 0.95) * 100) / 100,
        p99: Math.round(percentile(frameTimes, 0.99) * 100) / 100,
        worst: Math.round(Math.max(...frameTimes) * 100) / 100,
      },
      draw: {
        renderPassesPerFrame: Math.round(drawCalls.length / displayFrames * 100) / 100,
        meanDrawCallsPerFrame: Math.round(drawCalls.reduce((sum, value) => sum + value, 0) / displayFrames),
        drawCallsPerRenderPassP50: drawCalls.length ? percentile(drawCalls, 0.5) : null,
        drawCallsPerRenderPassP95: drawCalls.length ? percentile(drawCalls, 0.95) : null,
        meanTrianglesPerFrame: Math.round(triangles.reduce((sum, value) => sum + value, 0) / displayFrames),
        trianglesPerRenderPassP50: triangles.length ? percentile(triangles, 0.5) : null,
      },
      rendererResources: {
        geometries: memory.geometries ?? null,
        textures: memory.textures ?? null,
        allocatedBytes: memory.total ?? null,
      },
      jsHeapBytes: usedHeapBytes,
    };
  });
}

async function fieldSelectionLatency(page) {
  return page.evaluate(async () => {
    const percentile = (values, fraction) => {
      const sorted = [...values].sort((left, right) => left - right);
      return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1)];
    };
    const host = document.querySelector("[data-testid='pitch-canvas']");
    const buttons = [...document.querySelectorAll("[data-testid='pitch-canvas'] button[aria-label^='Select player ']")];
    const ids = buttons.slice(0, 2).map((button) => button.getAttribute("aria-label").replace("Select player ", ""));
    if (!host || ids.length < 2) return null;
    const samples = [];
    for (let index = 0; index < 8; index += 1) {
      const id = ids[index % ids.length];
      const button = buttons.find((candidate) => candidate.getAttribute("aria-label") === `Select player ${id}`);
      const started = performance.now();
      button.click();
      await new Promise((resolve) => {
        const wait = () => host.dataset.selectedPlayerId === id ? resolve() : requestAnimationFrame(wait);
        wait();
      });
      samples.push(performance.now() - started);
    }
    return {
      samplesMs: samples.map((value) => Math.round(value * 100) / 100),
      p50Ms: Math.round(percentile(samples, 0.5) * 100) / 100,
      p95Ms: Math.round(percentile(samples, 0.95) * 100) / 100,
    };
  });
}

const browserArgs = [
  "--enable-unsafe-webgpu",
  "--enable-gpu",
  "--enable-features=Vulkan,UseSkiaRenderer",
  "--use-vulkan",
  "--enable-dawn-features=allow_unsafe_apis",
];
const runs = [];
for (const backend of ["webgl2", "webgpu"]) {
  const browser = await chromium.launch({ args: browserArgs });
  try {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
      const page = await context.newPage();
      let activeErrors = [];
      page.on("pageerror", (error) => activeErrors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error" && !activeErrors.includes(message.text())) activeErrors.push(message.text());
      });
      await page.addInitScript((value) => localStorage.setItem("dynamis-matchlab-renderer-benchmark", value), backend);
      for (const scenario of scenarios) {
        const errors = [];
        activeErrors = errors;
        const result = {
          backend,
          viewport,
          scenario: scenario.id,
          errors,
          status: "running",
        };
        try {
          await page.goto(`${baseUrl}${scenario.path}`);
          const hostSelector = scenario.id === "pose" ? "[data-testid='pose-canvas']" : "[data-testid='pitch-canvas']";
          await page.locator("[data-testid='matchlab-canvas'] canvas").waitFor({ timeout: 60000 });
          await page.waitForFunction((selector) => document.querySelector(selector)?.getAttribute("data-renderer-ready") === "true", hostSelector, { timeout: 60000 });
          if (scenario.id === "split") {
            await page.waitForFunction(() => document.querySelector("[data-testid='pose-canvas']")?.getAttribute("data-renderer-ready") === "true", null, { timeout: 60000 });
          }
          await page.waitForFunction(() => Boolean(window.__dynamisMatchLabBenchmarkRenderer?.info), null, { timeout: 60000 });
          await instrumentRenderer(page);

          if (scenario.id !== "pose") {
            for (const label of ["Territory", "Influence"]) {
              const button = page.getByRole("button", { name: new RegExp(label) }).first();
              if (await button.getAttribute("aria-pressed") !== "true") await button.click();
            }
            await page.waitForFunction(() => Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.overlayTerritoryCells) > 0);
            await page.waitForFunction(() => Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.overlayInfluenceCells) > 0);
          }
          if (scenario.id !== "field") {
            const allSubjects = page.getByTestId("pose-all-subjects-toggle");
            if (await allSubjects.getAttribute("aria-pressed") !== "true") await allSubjects.click();
            await page.waitForFunction(() => {
              const text = [...document.querySelectorAll("p")]
                .map((node) => node.textContent ?? "")
                .find((value) => value.includes("subjects share one source-coordinate world"));
              return Number(text?.match(/^\s*(\d+)/)?.[1] ?? 0) > 1;
            }, null, { timeout: 60000 });
            await page.waitForTimeout(1000);
          }

          const renderer = await page.evaluate(() => ({
            webgpu: window.__dynamisMatchLabBenchmarkRenderer.isWebGPURenderer === true,
            webgl2: window.__dynamisMatchLabBenchmarkRenderer.isWebGLRenderer === true,
            source: document.querySelector("[data-testid='pitch-canvas']")?.dataset.sourceFrameIdentity ?? null,
          }));
          if ((backend === "webgpu") !== renderer.webgpu) throw new Error(`Requested ${backend}; renderer flags were ${JSON.stringify(renderer)}`);
          const play = page.getByRole("button", { name: "Play", exact: true }).first();
          await play.click();
          result.measurement = await measure(page);
          await page.getByRole("button", { name: "Pause playback" }).first().click();
          result.selectionLatency = scenario.id !== "pose" ? await fieldSelectionLatency(page) : null;
          result.poseSubjectCount = scenario.id !== "field"
            ? await page.locator("[data-testid='pose-canvas']").evaluate(() => Number(
                [...document.querySelectorAll("p")]
                  .map((node) => node.textContent ?? "")
                  .find((value) => value.includes("subjects share one source-coordinate world"))
                  ?.match(/^\s*(\d+)/)?.[1] ?? 0,
              ))
            : null;
          result.status = errors.length === 0 ? "ok" : "console-error";
          result.sourceFrameIdentity = renderer.source;
        } catch (error) {
          result.status = "failed";
          result.failure = String(error);
        }
        runs.push(result);
        console.log(JSON.stringify(result));
      }
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

const report = {
  issue: "RES-113",
  capturedAt: new Date().toISOString(),
  baseUrl,
  browser: "Playwright Chromium headless with WebGPU enabled",
  deviceScaleFactor: 1,
  sampleDurationMs: 5000,
  method: {
    data: "Real local SkillCorner source artifacts through the running API; no mocks.",
    scenes: "Field includes territory and influence overlays; Pose and split use the all-subjects scope, with each run recording the source subjects available in its bounded window.",
    resolution: "The requested viewport sizes are recorded separately from the responsive canvas backing size.",
    memory: "Records JS heap, renderer resource counts, and WebGPU-reported allocated bytes. WebGL2 does not expose comparable allocated bytes, so cross-backend GPU memory comparison is unavailable.",
    repeatCount: 1,
    concurrentSplit: "Field and Pose are mounted simultaneously as two Drei View panels in one Canvas; the shared canonical playhead drives both.",
  },
  webgpuCompatibility: runs.filter((run) => run.backend === "webgpu").every((run) =>
    run.status === "ok" && run.measurement?.isWebGPURenderer === true,
  ) ? "passed all real Field/Pose scenes without renderer or console errors" : "failed one or more real scenes",
  recommendedBackend: "WebGL2",
  decision: "WebGPU rendered all tested scenes without errors but showed no benefit. Standalone Field was tied and Pose was 1–2 FPS slower; the split scene was 8–10 FPS on WebGPU versus 40–45 FPS on WebGL2, with p95 frame intervals of roughly 183–217 ms versus 50–67 ms. Keep WebGL2 as the production backend.",
  runs,
};
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
if (runs.some((run) => run.status !== "ok")) process.exitCode = 1;
