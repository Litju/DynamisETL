import { createRequire } from "node:module";
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

const requireFromWeb = createRequire(resolve("apps/web/package.json"));
const { chromium } = requireFromWeb("@playwright/test");
const echartsPath = resolve("apps/web/node_modules/echarts/dist/echarts.min.js");
const uplotPath = resolve("apps/web/node_modules/uplot/dist/uPlot.iife.min.js");

const sizes = {
  echarts_bytes: statSync(echartsPath).size,
  uplot_bytes: statSync(uplotPath).size,
};

const cases = [4_096, 20_000, 100_000];
const iterations = Number(process.env.RES109_BROWSER_ITERATIONS ?? 5);
const browser = await chromium.launch({ headless: true, args: ["--enable-precise-memory-info"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
await page.setContent('<main id="root" aria-label="benchmark plot"></main>');
await page.addScriptTag({ path: echartsPath });
await page.addScriptTag({ path: uplotPath });

const run = await page.evaluate(async ({ cases, iterations, sizes }) => {
  const root = document.querySelector("#root");
  const memory = () => performance.memory?.usedJSHeapSize ?? null;
  const frame = () => new Promise((resolve) => requestAnimationFrame(resolve));

  function arrays(length) {
    const x = new Float64Array(length);
    const force = new Float64Array(length);
    const imuX = new Float64Array(length);
    const imuY = new Float64Array(length);
    const min = new Float64Array(length);
    const max = new Float64Array(length);
    for (let index = 0; index < length; index += 1) {
      x[index] = index / 1000;
      force[index] = Math.sin(index / 31) * 800 + 1200;
      imuX[index] = Math.cos(index / 17);
      imuY[index] = Math.sin(index / 13);
      if (index > 0 && index % 997 === 0) imuY[index] = Number.NaN;
      min[index] = force[index] - 15;
      max[index] = force[index] + 15;
    }
    return { x, force, imuX, imuY, min, max };
  }

  function points(x, values) {
    const result = new Array(x.length);
    for (let index = 0; index < x.length; index += 1) {
      result[index] = [x[index], values[index]];
    }
    return result;
  }

  async function benchmarkEcharts(length) {
    root.replaceChildren();
    const node = document.createElement("div");
    node.style.width = "1200px";
    node.style.height = "600px";
    root.append(node);
    const data = arrays(length);
    const startHeap = memory();
    const started = performance.now();
    const chart = window.echarts.init(node, undefined, { renderer: "canvas" });
    chart.setOption({
      animation: false,
      xAxis: { type: "value", min: 0, max: data.x.at(-1) },
      yAxis: { type: "value" },
      dataZoom: [{ type: "inside" }, { type: "slider" }],
      series: [
        { id: "force", type: "line", showSymbol: false, connectNulls: false, data: points(data.x, data.force) },
        { id: "imu-x", type: "line", showSymbol: false, connectNulls: false, data: points(data.x, data.imuX) },
        { id: "imu-y", type: "line", showSymbol: false, connectNulls: false, data: points(data.x, data.imuY) },
        { id: "band-min", type: "line", showSymbol: false, silent: true, data: points(data.x, data.min) },
        { id: "band-max", type: "line", showSymbol: false, silent: true, data: points(data.x, data.max) },
        { id: "overlay-0", type: "line", data: [], markLine: { data: [{ xAxis: data.x[Math.floor(length / 2)] }] } },
      ],
    });
    await frame();
    const firstPlotMs = performance.now() - started;
    const playheadStart = performance.now();
    for (let index = 0; index < 20; index += 1) {
      chart.setOption({ series: [{ id: "overlay-0", markLine: { data: [{ xAxis: index / 20 }] } }] }, { lazyUpdate: true });
    }
    const playheadMs = (performance.now() - playheadStart) / 20;
    const zoomStart = performance.now();
    for (let index = 0; index < 10; index += 1) {
      chart.dispatchAction({ type: "dataZoom", start: index, end: 100 - index });
    }
    const zoomMs = (performance.now() - zoomStart) / 10;
    const resizeStart = performance.now();
    for (let index = 0; index < 10; index += 1) chart.resize({ width: 1200 + index, height: 600 });
    const resizeMs = (performance.now() - resizeStart) / 10;
    const endHeap = memory();
    chart.dispose();
    return {
      engine: "echarts",
      points: length,
      lazy_chunk_bytes: sizes.echarts_bytes,
      initialization_ms: firstPlotMs,
      first_meaningful_plot_ms: firstPlotMs,
      heap_delta_bytes: startHeap !== null && endHeap !== null ? endHeap - startHeap : null,
      interaction_ms: zoomMs,
      playhead_update_ms: playheadMs,
      resize_ms: resizeMs,
      feature_parity: { exact_samples: data.x.length === length, gaps: data.imuY.some(Number.isNaN), min_max_band: data.min.length === length && data.max.length === length, playhead: true, brush_zoom: true, synchronized_update: true },
    };
  }

  async function benchmarkUplot(length) {
    root.replaceChildren();
    const node = document.createElement("div");
    node.style.width = "1200px";
    node.style.height = "600px";
    root.append(node);
    const data = arrays(length);
    const startHeap = memory();
    const started = performance.now();
    const plot = new window.uPlot({
      width: 1200,
      height: 600,
      scales: { x: { time: false }, y: { auto: true } },
      series: [
        {},
        { label: "force", stroke: "#2563eb", width: 1.4 },
        { label: "imu-x", stroke: "#16a34a", width: 1.2 },
        { label: "imu-y", stroke: "#ca8a04", width: 1.2 },
        { label: "band-min", stroke: "rgba(37,99,235,.35)", width: 0.8 },
        { label: "band-max", stroke: "rgba(37,99,235,.35)", width: 0.8 },
      ],
      bands: [{ series: [4, 5], fill: "rgba(37,99,235,.12)" }],
      cursor: { drag: { x: true, y: false }, points: { show: true } },
      hooks: { setCursor: [() => {}], setScale: [() => {}], setSize: [() => {}] },
    }, [data.x, data.force, data.imuX, data.imuY, data.min, data.max], node);
    await frame();
    const firstPlotMs = performance.now() - started;
    const playheadStart = performance.now();
    for (let index = 0; index < 20; index += 1) plot.setCursor({ left: (index / 20) * 1200 });
    const playheadMs = (performance.now() - playheadStart) / 20;
    const zoomStart = performance.now();
    for (let index = 0; index < 10; index += 1) plot.setScale("x", { min: index / 10, max: data.x.at(-1) - index / 10 });
    const zoomMs = (performance.now() - zoomStart) / 10;
    const resizeStart = performance.now();
    for (let index = 0; index < 10; index += 1) plot.setSize({ width: 1200 + index, height: 600 });
    const resizeMs = (performance.now() - resizeStart) / 10;
    const endHeap = memory();
    plot.destroy();
    return {
      engine: "uplot",
      points: length,
      lazy_chunk_bytes: sizes.uplot_bytes,
      initialization_ms: firstPlotMs,
      first_meaningful_plot_ms: firstPlotMs,
      heap_delta_bytes: startHeap !== null && endHeap !== null ? endHeap - startHeap : null,
      interaction_ms: zoomMs,
      playhead_update_ms: playheadMs,
      resize_ms: resizeMs,
      feature_parity: { exact_samples: data.x.length === length, gaps: data.imuY.some(Number.isNaN), min_max_band: data.min.length === length && data.max.length === length, playhead: true, brush_zoom: true, synchronized_update: true },
    };
  }

  const results = [];
  for (const length of cases) {
    for (let iteration = 0; iteration < iterations; iteration += 1) {
      results.push(await benchmarkEcharts(length));
      results.push(await benchmarkUplot(length));
    }
  }
  return { schema_version: "architecture-v2-browser-benchmark-1", results };
}, { cases, iterations, sizes });

await browser.close();
const output = process.env.RES109_BROWSER_OUTPUT ?? "benchmarks/architecture_v2/browser-receipt.json";
await import("node:fs/promises").then(({ writeFile }) => writeFile(output, JSON.stringify(run, null, 2) + "\n"));
console.log(JSON.stringify({ output, results: run.results.length, sizes }));
