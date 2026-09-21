import { createRequire } from "node:module";
import { resolve } from "node:path";

const requireFromWeb = createRequire(resolve("apps/web/package.json"));
const { chromium } = requireFromWeb("@playwright/test");
const browser = await chromium.launch({
  headless: true,
  args: ["--enable-unsafe-webgpu", "--use-angle=swiftshader", "--enable-features=Vulkan"],
});
const page = await browser.newPage();
await page.setContent('<canvas id="canvas" width="320" height="240"></canvas>');
const result = await page.evaluate(() => {
  const canvas = document.querySelector("#canvas");
  const webgl2 = canvas?.getContext("webgl2") !== null;
  const webgpu = typeof navigator.gpu !== "undefined";
  return { webgl2, webgpu, user_agent: navigator.userAgent };
});
await browser.close();
const output = process.env.RES109_WEBGPU_OUTPUT ?? "benchmarks/architecture_v2/webgpu-receipt.json";
const receipt = {
  schema_version: "architecture-v2-webgpu-probe-1",
  result,
  decision: result.webgpu && result.webgl2 ? "requires_optimized_scene_measurement" : "freeze_webgl2_with_future_webgpu_seam",
};
await import("node:fs/promises").then(({ writeFile }) => writeFile(output, JSON.stringify(receipt, null, 2) + "\n"));
console.log(JSON.stringify({ output, ...result, decision: receipt.decision }));
