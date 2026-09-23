import { mkdir } from "node:fs/promises";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

/**
 * Shared real-data helpers. Every route hits the real local API through the
 * Vite proxy; nothing is intercepted.
 */
export const DFL = "/lab/dfl-sportec-idsse/DFL-MAT-J03WPY";
export const SC = "/lab/skillcorner-opendata/1925299";

/** Console messages tolerated on flagship paths (ACCEPTANCE-MATRIX.md, FP-02). */
const ALLOWED_CONSOLE = [
  /THREE\.Clock: This module has been deprecated/,
  /GPU stall due to ReadPixels/,
  /\[vite\]/,
  /React DevTools/,
];

export interface ConsoleProbe {
  readonly errors: string[];
  readonly warnings: string[];
  readonly api: string[];
  readonly failed: string[];
}

export function probe(page: Page): ConsoleProbe {
  const result: ConsoleProbe = { errors: [], warnings: [], api: [], failed: [] };
  page.on("console", (message) => {
    const text = message.text();
    if (ALLOWED_CONSOLE.some((pattern) => pattern.test(text))) return;
    if (message.type() === "error") result.errors.push(text);
    if (message.type() === "warning") result.warnings.push(text);
  });
  page.on("pageerror", (error) => result.errors.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api/")) {
      result.api.push(`${response.status()} ${url.pathname}${url.search}`);
      if (response.status() >= 500) result.failed.push(`${response.status()} ${url.pathname}`);
    }
  });
  return result;
}

export async function expectCleanConsole(result: ConsoleProbe) {
  expect(result.errors, "console errors / page errors on a flagship path").toEqual([]);
  expect(result.failed, "API 5xx responses").toEqual([]);
}

export async function waitForPitch(page: Page) {
  const canvas = page.getByTestId("pitch-canvas");
  await expect(canvas).toHaveAttribute("data-renderer-ready", "true");
  await expect(canvas).not.toHaveAttribute("data-frame-ns", "");
  return canvas;
}

export async function playheadNs(page: Page): Promise<bigint | null> {
  const text = (await page.getByTestId("playhead-ns").textContent()) ?? "";
  const match = /(-?\d+) ns/.exec(text);
  return match ? BigInt(match[1]!) : null;
}

export const EVIDENCE = path.resolve(process.cwd(), "../../output/playwright/res-112/after");

export async function evidence(page: Page, name: string) {
  await mkdir(EVIDENCE, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE, `${name}.png`) });
}

/** Count distinct pitch canvases and API requests over a playback interval. */
export async function measurePlayback(page: Page, milliseconds: number) {
  await page.evaluate(() => {
    const host = document.querySelector("[data-testid='pitch-canvas'], [data-testid='pose-canvas']");
    const seen = new Set<Element | null>([host?.querySelector("canvas") ?? null]);
    const state = { seen, stop: false, frames: 0 };
    const tick = () => {
      state.frames += 1;
      seen.add(host?.querySelector("canvas") ?? null);
      if (!state.stop) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    (window as unknown as { __res112Playback: typeof state }).__res112Playback = state;
  });
  await page.waitForTimeout(milliseconds);
  return page.evaluate(() => {
    const state = (window as unknown as { __res112Playback: { seen: Set<unknown>; stop: boolean; frames: number } }).__res112Playback;
    state.stop = true;
    return { distinctCanvases: state.seen.size, animationFrames: state.frames };
  });
}
