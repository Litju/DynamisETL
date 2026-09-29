/* global WebGL2RenderingContext, document, requestAnimationFrame, window */

import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { gzipSync } from "node:zlib";
import { chromium } from "@playwright/test";

const appDir = path.resolve(import.meta.dirname, "..");
const output = path.resolve(appDir, "../../output/playwright/res-129/final/production-benchmark.json");
const baseUrl = process.env.DYNAMIS_BENCHMARK_BASE_URL ?? "http://127.0.0.1:4174";
const apiBase = process.env.DYNAMIS_API_TARGET ?? "http://127.0.0.1:8000";
const viewports = [{ width: 1600, height: 1000 }, { width: 1440, height: 900 }];
const repeatCount = 3;
const warmupMs = 2000;
const sampleMs = 5000;
const scenarios = [
  { id: "field", path: "/lab/skillcorner-opendata/1925299?view=field&stream=tracking-period-1&subject=11897&t_ns=0" },
  { id: "pose", path: "/lab/skillcorner-opendata/1925299?view=pose&stream=pose-period-1&subject=11897&t_ns=440000000" },
  { id: "split", path: "/lab/skillcorner-opendata/1925299?view=split&stream=tracking-period-1&subject=11897&t_ns=5000000000" },
];
const seasonPath = "/season?edition=edition-ebf871f2a9cd29912d68880e&family=physical&team=team-6db2746c59daa23a45580196&player=skillcorner-opendata%2F966112";

const metricScript = () => {
  const metrics = { active: false, contexts: [], longTasks: [] };
  const contextStates = new WeakMap();
  const contextState = (gl) => {
    let state = contextStates.get(gl);
    if (!state) {
      const debug = gl.getExtension("WEBGL_debug_renderer_info");
      state = {
        canvas: gl.canvas,
        renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
        version: gl.getParameter(gl.VERSION),
        attributes: gl.getContextAttributes(),
        maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
        drawCalls: 0,
        triangles: 0,
        cpuSubmissionMs: 0,
        created: { buffers: 0, textures: 0, framebuffers: 0, renderbuffers: 0 },
        frameDrawCalls: 0,
        frameTriangles: 0,
      };
      metrics.contexts.push(state);
      contextStates.set(gl, state);
    }
    return state;
  };
  const triangles = (mode, count) => mode === 4 ? Math.floor(count / 3) : mode === 5 || mode === 6 ? Math.max(0, count - 2) : 0;
  const drawMethods = {
    drawElements: (args) => [args[0], args[1]],
    drawArrays: (args) => [args[0], args[2]],
    drawElementsInstanced: (args) => [args[0], args[1] * args[4]],
    drawArraysInstanced: (args) => [args[0], args[2] * args[3]],
  };
  for (const [name, getDraw] of Object.entries(drawMethods)) {
    const original = WebGL2RenderingContext.prototype[name];
    if (!original) continue;
    WebGL2RenderingContext.prototype[name] = function (...args) {
      if (!metrics.active) return original.apply(this, args);
      const startedAt = performance.now();
      const result = original.apply(this, args);
      const state = contextState(this);
      const [mode, count] = getDraw(args);
      state.drawCalls += 1;
      state.frameDrawCalls += 1;
      state.triangles += triangles(mode, count);
      state.frameTriangles += triangles(mode, count);
      state.cpuSubmissionMs += performance.now() - startedAt;
      return result;
    };
  }
  for (const [name, key] of [["createBuffer", "buffers"], ["createTexture", "textures"], ["createFramebuffer", "framebuffers"], ["createRenderbuffer", "renderbuffers"]]) {
    const original = WebGL2RenderingContext.prototype[name];
    WebGL2RenderingContext.prototype[name] = function (...args) {
      const result = original.apply(this, args);
      contextState(this).created[key] += 1;
      return result;
    };
  }
  const observer = new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) metrics.longTasks.push({ startTime: entry.startTime, duration: entry.duration });
  });
  try {
    observer.observe({ type: "longtask", buffered: true });
  } catch {
    metrics.longTaskObservationUnsupported = true;
  }
  Object.defineProperty(window, "__res129ProductionMetrics", { value: metrics });
};

async function openPage(browser, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: "reduce" });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !/server responded with a status of (?:404|451|503)\b/u.test(message.text())) errors.push(message.text());
  });
  await page.addInitScript(metricScript);
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    return route.fulfill({ response: await route.fetch({ url: `${apiBase}${url.pathname}${url.search}` }) });
  });
  return { context, page, errors };
}

async function enableFieldOverlays(page) {
  for (const label of ["Territory", "Influence"]) {
    const button = page.getByRole("button", { name: new RegExp(label) }).first();
    if (await button.getAttribute("aria-pressed") !== "true") await button.click();
  }
  await page.waitForFunction(() => Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.overlayTerritoryCells) > 0);
  await page.waitForFunction(() => Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.overlayInfluenceCells) > 0);
}

async function summarizeRenderer(page, warmup, sample) {
  return page.evaluate(async ({ warmupMs: warmupDuration, sampleMs: sampleDuration }) => {
    const metrics = window.__res129ProductionMetrics;
    const percentile = (values, fraction) => {
      const sorted = [...values].sort((a, b) => a - b);
      return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1)] ?? null;
    };
    const round = (value) => value == null ? null : Math.round(value * 100) / 100;
    const scripts = () => performance.getEntriesByType("resource")
      .filter((entry) => entry.initiatorType === "script" && /\.js(?:\?|$)/u.test(entry.name))
      .map((entry) => ({
        file: new URL(entry.name).pathname.split("/").at(-1),
        startMs: round(entry.startTime),
        responseEndMs: round(entry.responseEnd),
        durationMs: round(entry.duration),
        transferBytes: entry.transferSize || null,
        encodedBytes: entry.encodedBodySize || null,
      }));
    await new Promise((resolve) => setTimeout(resolve, warmupDuration));
    for (const state of metrics.contexts) {
      state.drawCalls = 0;
      state.triangles = 0;
      state.cpuSubmissionMs = 0;
      state.frameDrawCalls = 0;
      state.frameTriangles = 0;
    }
    metrics.longTasks.length = 0;
    const frameIntervals = [];
    const drawCallsPerFrame = [];
    const trianglesPerFrame = [];
    let previousFrame = null;
    const startedAt = performance.now();
    metrics.active = true;
    await new Promise((resolve) => {
      const frame = (time) => {
        if (previousFrame !== null) {
          frameIntervals.push(time - previousFrame);
          drawCallsPerFrame.push(metrics.contexts.reduce((sum, state) => sum + state.frameDrawCalls, 0));
          trianglesPerFrame.push(metrics.contexts.reduce((sum, state) => sum + state.frameTriangles, 0));
          for (const state of metrics.contexts) {
            state.frameDrawCalls = 0;
            state.frameTriangles = 0;
          }
        }
        previousFrame = time;
        if (time - startedAt < sampleDuration) requestAnimationFrame(frame);
        else resolve();
      };
      requestAnimationFrame(frame);
    });
    const elapsedMs = performance.now() - startedAt;
    metrics.active = false;
    const contexts = metrics.contexts.map((state) => ({
      canvas: { width: state.canvas.width, height: state.canvas.height },
      renderer: state.renderer,
      version: state.version,
      attributes: state.attributes,
      maxTextureSize: state.maxTextureSize,
      drawCalls: state.drawCalls,
      triangles: state.triangles,
      cpuSubmissionMs: round(state.cpuSubmissionMs),
      resourcesCreated: state.created,
    }));
    const nav = performance.getEntriesByType("navigation")[0];
    return {
      elapsedMs: Math.round(elapsedMs),
      frames: frameIntervals.length,
      fps: round(frameIntervals.length * 1000 / elapsedMs),
      frameIntervalMs: {
        p50: round(percentile(frameIntervals, 0.5)),
        p95: round(percentile(frameIntervals, 0.95)),
        p99: round(percentile(frameIntervals, 0.99)),
        worst: round(Math.max(...frameIntervals)),
      },
      render: {
        drawCalls: contexts.reduce((sum, state) => sum + state.drawCalls, 0),
        drawCallsPerFrame: round(percentile(drawCallsPerFrame, 0.5)),
        drawCallsPerFrameP95: round(percentile(drawCallsPerFrame, 0.95)),
        triangles: contexts.reduce((sum, state) => sum + state.triangles, 0),
        trianglesPerFrameP50: round(percentile(trianglesPerFrame, 0.5)),
        glCpuSubmissionMs: round(contexts.reduce((sum, state) => sum + (state.cpuSubmissionMs ?? 0), 0)),
        longTaskCount: metrics.longTasks.filter((entry) => entry.startTime >= startedAt && entry.startTime <= startedAt + elapsedMs).length,
        rendererResources: contexts.map((state) => state.resourcesCreated),
        allocatedGpuBytes: null,
        allocatedGpuBytesReason: "WebGL2 does not expose total device allocation.",
      },
      gpu: {
        webgl2ContextCount: contexts.length,
        contexts,
        softwareRendererDetected: contexts.some((context) => /swiftshader|llvmpipe|software renderer/iu.test(context.renderer ?? "")),
      },
      jsHeapBytes: performance.memory?.usedJSHeapSize ?? null,
      navigation: nav ? {
        domContentLoadedMs: round(nav.domContentLoadedEventEnd),
        loadEventMs: round(nav.loadEventEnd),
      } : null,
      scriptTimings: scripts(),
      echartsLoadedAtUsefulRender: scripts().some((entry) => /echarts/iu.test(entry.file)),
    };
  }, { warmupMs: warmup, sampleMs: sample });
}

function median(values) {
  const sorted = values.toSorted((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

const gpuArgs = ["--enable-gpu", "--use-gl=angle", "--use-angle=d3d11", "--force-high-performance-gpu"];
const browser = await chromium.launch({ args: gpuArgs });
const runs = [];
const lazyChartRuns = [];
if (process.env.RES129_CHUNKS_ONLY === "1") {
  const previous = JSON.parse(await readFile(output, "utf8"));
  if (previous.runs?.length !== viewports.length * scenarios.length * repeatCount) throw new Error("Existing production renderer matrix is incomplete.");
  runs.push(...previous.runs);
}
try {
  for (const viewport of process.env.RES129_CHUNKS_ONLY === "1" ? [] : viewports) {
    for (const scenario of scenarios) {
      for (let repeat = 1; repeat <= repeatCount; repeat += 1) {
        const { context, page, errors } = await openPage(browser, viewport);
        const startedAt = Date.now();
        const run = { viewport, scenario: scenario.id, repeat, status: "running", errors };
        try {
          await page.goto(`${baseUrl}${scenario.path}`);
          const primary = scenario.id === "pose" ? "pose-canvas" : "pitch-canvas";
          await page.waitForFunction((id) => document.querySelector(`[data-testid='${id}']`)?.getAttribute("data-renderer-ready") === "true", primary, { timeout: 60000 });
          if (scenario.id === "split") await page.waitForFunction(() => document.querySelector("[data-testid='pose-canvas']")?.getAttribute("data-renderer-ready") === "true", null, { timeout: 60000 });
          if (scenario.id !== "pose") await enableFieldOverlays(page);
          if (scenario.id === "pose") {
            const allSubjects = page.getByTestId("pose-all-subjects-toggle");
            if (await allSubjects.getAttribute("aria-pressed") !== "true") await allSubjects.click();
            await page.waitForFunction(() => [...document.querySelectorAll("p")].some((node) => /subjects share one source-coordinate world/u.test(node.textContent ?? "")));
          }
          run.usefulWorldReadyMs = Date.now() - startedAt;
          await page.getByRole("button", { name: "Play", exact: true }).first().click();
          run.measurement = await summarizeRenderer(page, warmupMs, sampleMs);
          const hardware = run.measurement.gpu.contexts.every((item) => /amd|radeon/iu.test(item.renderer ?? "") && /d3d11|direct3d/iu.test(item.renderer ?? ""));
          if (!hardware || run.measurement.gpu.softwareRendererDetected) throw new Error(`Hardware WebGL2 was not confirmed: ${JSON.stringify(run.measurement.gpu.contexts.map((item) => item.renderer))}`);
          if (run.measurement.gpu.webgl2ContextCount === 0) throw new Error("No production WebGL2 context was measured.");
          run.hardwareAccelerationConfirmed = true;
          run.status = errors.length === 0 ? "ok" : "console-error";
        } catch (error) {
          run.status = "failed";
          run.failure = String(error);
        }
        runs.push(run);
        console.log(JSON.stringify({ viewport, scenario: scenario.id, repeat, status: run.status, fps: run.measurement?.fps, p95Ms: run.measurement?.frameIntervalMs.p95, usefulWorldReadyMs: run.usefulWorldReadyMs, failure: run.failure }));
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await context.close();
      }
    }
  }

  for (const viewport of viewports) {
    for (let repeat = 1; repeat <= repeatCount; repeat += 1) {
      const { context, page, errors } = await openPage(browser, viewport);
      const run = { viewport, scenario: "season-echarts-lazy", repeat, status: "running", errors };
      const startedAt = Date.now();
      try {
        await page.goto(`${baseUrl}${seasonPath}`);
        const chart = page.locator('[data-renderer="echarts"]').first();
        await chart.waitFor({ state: "attached", timeout: 60000 });
        await page.waitForFunction(() => document.querySelector('[data-renderer="echarts"]')?.getAttribute("data-renderer-ready") === "true", null, { timeout: 60000 });
        run.chartReadyMs = Date.now() - startedAt;
        run.timings = await page.evaluate(() => performance.getEntriesByType("resource")
          .filter((entry) => /\/echarts-[^/]+\.js(?:\?|$)/iu.test(entry.name))
          .map((entry) => ({
            file: new URL(entry.name).pathname.split("/").at(-1),
            startMs: Math.round(entry.startTime * 100) / 100,
            responseEndMs: Math.round(entry.responseEnd * 100) / 100,
            networkDurationMs: Math.round(entry.duration * 100) / 100,
            transferBytes: entry.transferSize || null,
            encodedBytes: entry.encodedBodySize || null,
          })));
        if (!run.timings.length) throw new Error("SeasonLab chart became ready without loading the lazy ECharts chunk.");
        run.status = errors.length === 0 ? "ok" : "console-error";
      } catch (error) {
        run.status = "failed";
        run.failure = String(error);
      }
      lazyChartRuns.push(run);
      console.log(JSON.stringify({ viewport, scenario: run.scenario, repeat, status: run.status, chartReadyMs: run.chartReadyMs, timing: run.timings?.[0], failure: run.failure }));
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await context.close();
    }
  }
} finally {
  await browser.close();
}

const summaries = [];
for (const viewport of viewports) {
  for (const scenario of scenarios) {
    const matched = runs.filter((run) => run.status === "ok" && run.viewport.width === viewport.width && run.scenario === scenario.id);
    summaries.push({
      viewport,
      scenario: scenario.id,
      successfulRuns: matched.length,
      medianFps: matched.length ? median(matched.map((run) => run.measurement.fps)) : null,
      medianP95FrameIntervalMs: matched.length ? median(matched.map((run) => run.measurement.frameIntervalMs.p95)) : null,
      medianUsefulWorldReadyMs: matched.length ? median(matched.map((run) => run.usefulWorldReadyMs)) : null,
      medianDrawCallsPerFrame: matched.length ? median(matched.map((run) => run.measurement.render.drawCallsPerFrame)) : null,
      medianTrianglesPerFrame: matched.length ? median(matched.map((run) => run.measurement.render.trianglesPerFrameP50)) : null,
      medianGlCpuSubmissionMsPerSample: matched.length ? median(matched.map((run) => run.measurement.render.glCpuSubmissionMs)) : null,
      medianLongTasks: matched.length ? median(matched.map((run) => run.measurement.render.longTaskCount)) : null,
      medianViewChunkNetworkMs: matched.length ? median(matched.map((run) => run.measurement.scriptTimings.find((entry) => /^View-/u.test(entry.file))?.durationMs ?? 0)) : null,
      hardwareRenderer: matched[0]?.measurement.gpu.contexts.map((context) => context.renderer) ?? [],
      echartsLoadedBeforeFirstUsefulRender: matched.some((run) => run.measurement.echartsLoadedAtUsefulRender),
    });
  }
}

const echartsFile = (await readdir(path.resolve(appDir, "dist/assets"))).find((name) => /^echarts-[^/]+\.js$/u.test(name));
if (!echartsFile) throw new Error("Expected a production ECharts chunk.");
const echartsPath = path.resolve(appDir, "dist/assets", echartsFile);
const echartsBytes = (await stat(echartsPath)).size;
const echartsGzipBytes = gzipSync(await readFile(echartsPath)).length;
const lazyChartSummary = viewports.map((viewport) => {
  const matched = lazyChartRuns.filter((run) => run.status === "ok" && run.viewport.width === viewport.width);
  return {
    viewport,
    successfulRuns: matched.length,
    medianChartReadyMs: matched.length ? median(matched.map((run) => run.chartReadyMs)) : null,
    medianEchartsNetworkMs: matched.length ? median(matched.map((run) => run.timings[0].networkDurationMs)) : null,
    medianTransferBytes: matched.length ? median(matched.map((run) => run.timings[0].transferBytes ?? 0)) : null,
  };
});

const report = {
  issue: "RES-129",
  capturedAt: new Date().toISOString(),
  mode: "Vite production preview only; no test runner active.",
  baseUrl,
  apiBase,
  browser: "Playwright Chromium headless with AMD D3D11 hardware WebGL2",
  backend: "Production WebGL2 default; no dev benchmark renderer or WebGPU flag.",
  hardwareAccelerationConfirmed: runs.length > 0 && runs.every((run) => run.hardwareAccelerationConfirmed === true),
  repeatCount,
  warmupMs,
  sampleMs,
  viewportSizesCssPx: viewports,
  instrumentation: "Wraps WebGL2 draw and resource creation calls in the production page; records RAF intervals, triangles, GL submission time, long tasks, canvas context attributes, GPU renderer, JS heap, script resource timings, and first useful World render. GPU memory bytes are unavailable via WebGL2.",
  runs,
  summaries,
  lazyEcharts: {
    route: seasonPath,
    loadedOnlyAfterChartRoute: true,
    productionChunk: { file: echartsFile, rawBytes: echartsBytes, gzipBytes: echartsGzipBytes },
    runs: lazyChartRuns,
    summaries: lazyChartSummary,
  },
};
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify({ output, hardwareAccelerationConfirmed: report.hardwareAccelerationConfirmed, summaries, lazyEcharts: report.lazyEcharts }, null, 2));
if (runs.length !== viewports.length * scenarios.length * repeatCount || runs.some((run) => run.status !== "ok") || lazyChartRuns.length !== viewports.length * repeatCount || lazyChartRuns.some((run) => run.status !== "ok")) process.exitCode = 1;
