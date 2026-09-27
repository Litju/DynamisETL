#!/usr/bin/env node
// Capture real-app screenshots at workstation sizes for visual acceptance.
//
//   node scripts/capture.mjs <out-dir> <name>=<path>[@WxH] ...
//
// Each shot opens the path on DYNAMIS_CAPTURE_BASE_URL (default the dev server),
// waits for network idle, and fails if the page logged a console error.

import { mkdir } from "node:fs/promises";
import { join } from "node:path";

import { chromium } from "@playwright/test";

const base = process.env.DYNAMIS_CAPTURE_BASE_URL ?? "http://127.0.0.1:5190";
const [outDir, ...shots] = process.argv.slice(2);
if (!outDir || shots.length === 0) {
  console.error("usage: capture.mjs <out-dir> <name>=<path>[@WxH] ...");
  process.exit(2);
}
await mkdir(outDir, { recursive: true });

const browser = await chromium.launch();
let failures = 0;
for (const shot of shots) {
  const separator = shot.indexOf("=");
  const name = shot.slice(0, separator);
  const rest = shot.slice(separator + 1);
  const at = rest.lastIndexOf("@");
  const path = at === -1 ? rest : rest.slice(0, at);
  const size = at === -1 ? "1440x900" : rest.slice(at + 1);
  const [width, height] = size.split("x").map(Number);
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(new URL(path, base).toString(), { waitUntil: "networkidle" });
  await page.waitForTimeout(Number(process.env.DYNAMIS_CAPTURE_SETTLE_MS ?? 900));
  const scroll = Number(process.env.DYNAMIS_CAPTURE_SCROLL_MAIN ?? 0);
  if (scroll > 0) {
    await page.evaluate((top) => globalThis.document.querySelector("main main")?.scrollTo({ top }), scroll);
    await page.waitForTimeout(400);
  }
  const file = join(outDir, `${name}-${width}x${height}.png`);
  await page.screenshot({ path: file });
  console.log(`${file}${errors.length ? `  CONSOLE ERRORS: ${errors.join(" | ")}` : ""}`);
  if (errors.length) failures += 1;
  await page.close();
}
await browser.close();
process.exit(failures ? 1 : 0);
