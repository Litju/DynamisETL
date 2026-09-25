import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "@playwright/test";

/* global window, document, requestAnimationFrame */

const baseUrl = process.env.DYNAMIS_REAL_BASE_URL ?? "http://127.0.0.1:5173";
const output = path.resolve(process.cwd(), "../../output/playwright/res-113/hybrid-field-benchmark.json");
const evidenceDirectory = path.resolve(process.cwd(), "../../output/playwright/res-113/final");
const viewports = [{ width: 1600, height: 1000 }, { width: 1440, height: 900 }];
const fieldUrl = "/lab/dfl-sportec-idsse/DFL-MAT-J03WPY?view=field&stream=tracking-period-1&t_ns=300020000000&tactical=live";
const splitUrl = "/lab/skillcorner-opendata/1925299?view=split&stream=tracking-period-1&subject=11897&t_ns=120000000000&tactical=live";
const scenarios = [
  { id: "tactical_map", shadow: "off", surface: "heatmap" },
  { id: "structure_lift_shadow_off", shadow: "off", surface: "elevation" },
  { id: "structure_lift_shadow_on", shadow: "on", surface: "elevation" },
  { id: "split_field_orthographic_pose_3d", shadow: "off", surface: "heatmap" },
];

async function instrumentRenderer(page) {
  await page.evaluate(() => {
    const renderer = window.__dynamisMatchLabBenchmarkRenderer;
    if (!renderer?.info || renderer.__dynamisHybridBenchmarkWrapped) return;
    const info = renderer.info;
    info.autoReset = false;
    const stats = [];
    const shadowPasses = [];
    Object.assign(window, { __dynamisMatchLabFrameStats: stats, __dynamisMatchLabShadowPasses: shadowPasses });
    const shadowMap = renderer.shadowMap;
    if (typeof shadowMap?.render === "function") {
      const renderShadowMap = shadowMap.render.bind(shadowMap);
      shadowMap.render = (...args) => {
        const [lights] = args;
        const willRender = shadowMap.enabled && (shadowMap.autoUpdate || shadowMap.needsUpdate) &&
          Array.isArray(lights) && lights.some((light) => light?.castShadow === true && light.shadow);
        const startedAt = performance.now();
        const result = renderShadowMap(...args);
        if (willRender) shadowPasses.push(performance.now() - startedAt);
        return result;
      };
    }
    const render = renderer.render.bind(renderer);
    renderer.render = (...args) => {
      info.reset?.();
      const result = render(...args);
      const capture = () => stats.push({
        timestamp: performance.now(),
        drawCalls: info.render?.drawCalls ?? info.render?.calls ?? null,
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
    Object.assign(renderer, { __dynamisHybridBenchmarkWrapped: true });
  });
}

async function measure(page) {
  return page.evaluate(async () => {
    const percentile = (values, fraction) => {
      const sorted = [...values].sort((left, right) => left - right);
      return sorted.length === 0 ? null : sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1)];
    };
    const frameStats = window.__dynamisMatchLabFrameStats;
    const scalarUpdates = window.__dynamisMatchLabScalarSurfaceUpdates;
    const shadowPasses = window.__dynamisMatchLabShadowPasses;
    if (!frameStats) throw new Error("WebGL2 render instrumentation is unavailable");
    frameStats.length = 0;
    if (scalarUpdates) scalarUpdates.length = 0;
    if (shadowPasses) shadowPasses.length = 0;
    const frameIntervals = [];
    const startedAt = performance.now();
    let previous = null;
    await new Promise((resolve) => {
      const tick = (time) => {
        if (previous !== null) frameIntervals.push(time - previous);
        previous = time;
        if (time - startedAt < 5000) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });
    const elapsedMs = performance.now() - startedAt;
    const renderer = window.__dynamisMatchLabBenchmarkRenderer;
    const calls = frameStats.map((sample) => sample.drawCalls).filter((value) => typeof value === "number");
    const triangles = frameStats.map((sample) => sample.triangles).filter((value) => typeof value === "number");
    const scalar = scalarUpdates ?? [];
    const usedHeapBytes = performance.memory?.usedJSHeapSize ?? null;
    return {
      elapsedMs: Math.round(elapsedMs),
      fps: Math.round(frameIntervals.length * 1000 / elapsedMs),
      frameIntervalMs: {
        p50: percentile(frameIntervals, 0.5),
        p95: percentile(frameIntervals, 0.95),
        p99: percentile(frameIntervals, 0.99),
        worst: frameIntervals.length ? Math.max(...frameIntervals) : null,
      },
      renderPasses: frameStats.length,
      drawCallsPerRenderPass: {
        p50: percentile(calls, 0.5),
        p95: percentile(calls, 0.95),
        mean: calls.length ? calls.reduce((sum, value) => sum + value, 0) / calls.length : null,
      },
      trianglesPerRenderPassP50: percentile(triangles, 0.5),
      shadowPass: {
        samples: shadowPasses?.length ?? 0,
        durationMs: {
          p50: percentile(shadowPasses ?? [], 0.5),
          p95: percentile(shadowPasses ?? [], 0.95),
          max: shadowPasses?.length ? Math.max(...shadowPasses) : null,
        },
      },
      scalarSurfaceUpdate: {
        samples: scalar.length,
        validSamples: scalar.filter((sample) => sample.valid).length,
        cellsPerUpdate: scalar.length ? scalar[scalar.length - 1].cellCount : null,
        durationMs: {
          p50: percentile(scalar.map((sample) => sample.durationMs), 0.5),
          p95: percentile(scalar.map((sample) => sample.durationMs), 0.95),
          max: scalar.length ? Math.max(...scalar.map((sample) => sample.durationMs)) : null,
        },
      },
      jsHeapBytes: usedHeapBytes,
      fieldCameraMode: document.querySelector("[data-testid='pitch-canvas']")?.dataset.cameraMode ?? null,
      shadowEnabled: document.querySelector("[data-testid='pitch-canvas']")?.dataset.shadowEnabled === "true",
      scalarCellCount: Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.overlayInfluenceCells ?? 0),
      scalarSurfaceReady: document.querySelector("[data-testid='pitch-canvas']")?.dataset.scalarSurfaceReady === "true",
      scalarSurfaceVertices: Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.scalarSurfaceVertices ?? 0),
      renderer: {
        isWebGLRenderer: renderer?.isWebGLRenderer === true,
        isWebGPURenderer: renderer?.isWebGPURenderer === true,
      },
    };
  });
}

async function measureSelectionLatency(page) {
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
        requestAnimationFrame(wait);
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

const browser = await chromium.launch({
  args: [
    "--enable-gpu",
    "--use-gl=angle",
    "--use-angle=gl",
    "--enable-features=Vulkan,UseSkiaRenderer",
    "--enable-precise-memory-info",
  ],
});
const runs = [];
try {
  for (const viewport of viewports) {
    for (const scenario of scenarios) {
      const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
      await context.addInitScript(({ shadow }) => {
        localStorage.setItem("dynamis-matchlab-renderer-benchmark", "webgl2");
        localStorage.setItem("dynamis-matchlab-hybrid-benchmark", "1");
        if (shadow === "off") localStorage.setItem("dynamis-matchlab-field-shadow-benchmark", "off");
        else localStorage.removeItem("dynamis-matchlab-field-shadow-benchmark");
      }, scenario);
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      const result = { viewport, scenario: scenario.id, errors, status: "running" };
      try {
        const split = scenario.id === "split_field_orthographic_pose_3d";
        await page.goto(`${baseUrl}${split ? splitUrl : fieldUrl}`);
        const pitch = page.getByTestId("pitch-canvas");
        await page.waitForFunction(() => document.querySelector("[data-testid='pitch-canvas']")?.dataset.rendererReady === "true", null, { timeout: 60_000 });
        await page.waitForFunction(() => Boolean(window.__dynamisMatchLabBenchmarkRenderer?.info), null, { timeout: 60_000 });
        await page.waitForFunction(() => Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.v3UnitCount ?? 0) > 0, null, { timeout: 60_000 });
        for (const label of ["Territory", "Influence"]) {
          const button = page.getByRole("button", { name: new RegExp(label) }).first();
          if (await button.getAttribute("aria-pressed") !== "true") await button.click();
        }
        await page.waitForFunction(() => Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.overlayTerritoryCells ?? 0) > 0);
        await page.waitForFunction(() => Number(document.querySelector("[data-testid='pitch-canvas']")?.dataset.overlayInfluenceCells ?? 0) > 0);
        if (split) {
          await page.waitForFunction(() => document.querySelector("[data-testid='pose-canvas']")?.dataset.rendererReady === "true");
          await page.waitForFunction(() => document.querySelector("[data-testid='pose-canvas']")?.dataset.cameraProjection === "perspective");
        }
        await instrumentRenderer(page);

        if (scenario.id.startsWith("structure_lift")) {
          await page.getByRole("tab", { name: "Space" }).click();
          await page.getByLabel("Scalar field mode").selectOption("elevation");
          await page.getByRole("button", { name: "Structure Lift" }).click();
          await page.waitForFunction(() => document.querySelector("[data-testid='pitch-canvas']")?.dataset.cameraMode === "structure-lift");
          await page.waitForFunction(() => document.querySelector("[data-testid='pitch-canvas']")?.dataset.scalarSurfaceReady === "true", null, { timeout: 30_000 });
        } else {
          await page.getByRole("button", { name: "Tactical Map" }).click();
          await page.waitForFunction(() => document.querySelector("[data-testid='pitch-canvas']")?.dataset.cameraMode === "tactical-map");
        }
        const expectedShadows = scenario.shadow === "on";
        await page.waitForFunction((enabled) => document.querySelector("[data-testid='pitch-canvas']")?.dataset.shadowEnabled === String(enabled), expectedShadows);
        await page.waitForFunction(() => window.__dynamisMatchLabBenchmarkRenderer?.isWebGLRenderer === true);
        if (viewport.width === 1440 && scenario.id.startsWith("structure_lift")) {
          await mkdir(evidenceDirectory, { recursive: true });
          await page.screenshot({ path: path.join(evidenceDirectory, `benchmark-${scenario.id}.png`) });
        }

        result.selectionLatency = await measureSelectionLatency(page);
        if (result.selectionLatency === null) throw new Error("No tracked player labels were available for selection latency measurement");
        await page.getByRole("button", { name: "Play", exact: true }).first().click();
        await page.waitForTimeout(2000);
        result.measurement = await measure(page);
        await page.getByRole("button", { name: "Pause playback" }).first().click();
        if (scenario.id === "structure_lift_shadow_on" && result.measurement.shadowPass.samples === 0) {
          throw new Error("Structure Lift enabled shadows but produced no directional shadow-map pass");
        }
        if (scenario.shadow === "off" && result.measurement.shadowPass.samples !== 0) {
          throw new Error(`${scenario.id} unexpectedly rendered a shadow-map pass`);
        }
        result.sourceFrameIdentity = await pitch.getAttribute("data-source-frame-identity");
        result.status = errors.length === 0 ? "ok" : "console-error";
      } catch (error) {
        result.status = "failed";
        result.failure = String(error);
      }
      runs.push(result);
      console.log(JSON.stringify(result));
      await context.close();
    }
  }
} finally {
  await browser.close();
}

const byKey = new Map(runs.map((run) => [`${run.viewport.width}x${run.viewport.height}:${run.scenario}`, run]));
const shadowOverhead = viewports.map((viewport) => {
  const key = `${viewport.width}x${viewport.height}`;
  const shadowsOff = byKey.get(`${key}:structure_lift_shadow_off`);
  const shadowsOn = byKey.get(`${key}:structure_lift_shadow_on`);
  return {
    viewport,
    shadowOffFps: shadowsOff?.measurement?.fps ?? null,
    shadowOnFps: shadowsOn?.measurement?.fps ?? null,
    fpsDelta: shadowsOff?.measurement?.fps != null && shadowsOn?.measurement?.fps != null
      ? shadowsOn.measurement.fps - shadowsOff.measurement.fps
      : null,
    shadowOffFrameP95Ms: shadowsOff?.measurement?.frameIntervalMs?.p95 ?? null,
    shadowOnFrameP95Ms: shadowsOn?.measurement?.frameIntervalMs?.p95 ?? null,
    shadowOffDrawCallsP50: shadowsOff?.measurement?.drawCallsPerRenderPass?.p50 ?? null,
    shadowOnDrawCallsP50: shadowsOn?.measurement?.drawCallsPerRenderPass?.p50 ?? null,
    shadowPasses: shadowsOn?.measurement?.shadowPass?.samples ?? null,
    shadowPassDurationP50Ms: shadowsOn?.measurement?.shadowPass?.durationMs?.p50 ?? null,
    shadowPassDurationP95Ms: shadowsOn?.measurement?.shadowPass?.durationMs?.p95 ?? null,
  };
});

const report = {
  issue: "RES-113",
  capturedAt: new Date().toISOString(),
  baseUrl,
  backend: "WebGL2 production renderer",
  browser: "Playwright Chromium with hardware WebGL enabled",
  deviceScaleFactor: 1,
  sampleDurationMs: 5000,
  warmupDurationMs: 2000,
  method: {
    data: "Real local DFL/Sportec tracking and RES-110 tactical processor artifacts through the running API; no mocks.",
    scenarios: "Tactical Map with planar territory and heatmap; Structure Lift with the same planar overlays and metric ElevationSpec; paired Structure Lift runs disable/enable its sole directional shadow map; SkillCorner split with orthographic Field and true-3D Pose.",
    shadowOverhead: "Structure Lift camera and scalar surface remain identical; only the dev-only shadow benchmark switch changes.",
    scalarSurfaceUpdate: "Records main-thread duration for each typed-buffer grid-to-mesh update, including height/color writes, topology indices and normals.",
    frames: "Two seconds of playback warm-up, then five seconds measured per scenario; frame interval percentiles, Three render-pass draw calls, selection latency and actual shadow-map pass duration are recorded.",
    resolution: "Measured separately at 1600x1000 and 1440x900 CSS pixels.",
  },
  shadowOverhead,
  runs,
};
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, JSON.stringify(report, null, 2) + "\n");
if (runs.some((run) => run.status !== "ok")) process.exitCode = 1;
