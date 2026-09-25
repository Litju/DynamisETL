import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { DEFAULT_PITCH, pitchToScreen } from "../src/components/pitch/pitch-model";
import { DFL, expectCleanConsole, playheadNs, probe, waitForPitch } from "./helpers";

interface SessionStreams {
  readonly participants: readonly { readonly subject_id: string }[];
  readonly streams: readonly {
    readonly stream_id: string;
    readonly sample_artifact_ids: readonly string[];
  }[];
}

async function firstTrackedPlayer(page: Page): Promise<{ readonly id: string; readonly xM: number; readonly yM: number }> {
  const sessionResponse = await page.request.get("/api/catalog/datasets/dfl-sportec-idsse/sessions/DFL-MAT-J03WPY");
  expect(sessionResponse.ok()).toBe(true);
  const session = await sessionResponse.json() as SessionStreams;
  const stream = session.streams.find((item) => item.stream_id === "tracking-period-1")!;
  const response = await page.request.get(
    `/api/artifacts/${stream.sample_artifact_ids[0]}/window?from_ns=300020000000&to_ns=300020000000&columns=t_rel_ns%2Cobject_id%2Cobject_type%2Cx_m%2Cy_m&max_points=100`,
  );
  expect(response.ok()).toBe(true);
  const window = await response.json() as {
    readonly rows: readonly { readonly object_id: string; readonly object_type: string; readonly x_m: number; readonly y_m: number }[];
  };
  const participants = new Set(session.participants.map((participant) => participant.subject_id));
  const player = window.rows.find((row) =>
    participants.has(row.object_id) && (row.object_type === "player" || row.object_type === "goalkeeper"),
  );
  expect(player, "registered DFL player in exact reference frame").toBeDefined();
  return { id: player!.object_id, xM: player!.x_m, yM: player!.y_m };
}

async function captureRenderer(page: Page, mode: "pixi" | "r3f", player: { readonly id: string; readonly xM: number; readonly yM: number }) {
  const errors = probe(page);
  await page.addInitScript((value) => {
    if (value) window.localStorage.setItem("dynamis-matchlab-pixi-parity", "1");
    else window.localStorage.removeItem("dynamis-matchlab-pixi-parity");
  }, mode === "pixi");
  await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300020000000&from_ns=285000000000&to_ns=315000000000`);
  const host = await waitForPitch(page);
  await expect(host).toHaveAttribute("data-renderer", mode);
  for (const layer of ["Trails", "Labels", "Occupied area", "Territory", "Influence"]) {
    const button = page.getByRole("button", { name: new RegExp(layer) }).first();
    if (await button.getAttribute("aria-pressed") !== "true") await button.click();
  }
  await expect.poll(async () => Number(await host.getAttribute("data-overlay-territory-cells"))).toBeGreaterThan(15);
  await expect.poll(async () => Number(await host.getAttribute("data-overlay-influence-cells"))).toBeGreaterThan(100);
  await expect(host).toHaveAttribute("data-canonical-time-ns", "300020000000");
  await expect(host).toHaveAttribute("data-drawn-frame-ns", "300020000000");

  if (mode === "pixi") {
    const box = (await host.boundingBox())!;
    const scale = Math.min(box.width / (DEFAULT_PITCH.lengthM + 8), box.height / (DEFAULT_PITCH.widthM + 8));
    const point = pitchToScreen(player.xM, player.yM, {
      offsetX: box.width / 2,
      offsetY: box.height / 2,
      scale,
    });
    await page.mouse.click(box.x + point.x, box.y + point.y);
  } else {
    await page.getByRole("button", { name: `Select player ${player.id}`, exact: true }).click();
  }
  await expect(page).toHaveURL(new RegExp(`subject=${player.id}(?:&|$)`));
  await expect(page.getByTestId("pitch-selection")).toContainText(player.id);

  const eventsButton = page.getByRole("button", { name: "Events", exact: true }).first();
  if (await eventsButton.count()) {
    if (await eventsButton.getAttribute("aria-pressed") !== "true") await eventsButton.click();
  }
  const sourceEvents = await page.getByText(/\d+ source events in window/).textContent().catch(() => null);
  const snapshot = await page.evaluate(() => {
    const host = document.querySelector<HTMLElement>("[data-testid='pitch-canvas']")!;
    const selection = document.querySelector<HTMLElement>("[data-testid='pitch-selection']")?.innerText ?? "";
    const pressed = [...document.querySelectorAll<HTMLButtonElement>("[data-testid='pitch-canvas'] ~ * button[aria-pressed]")]
      .map((button) => [button.getAttribute("aria-label") ?? button.title ?? button.innerText, button.getAttribute("aria-pressed")]);
    return {
      renderer: host.dataset.renderer,
      canonicalTimeNs: host.dataset.canonicalTimeNs,
      sourceFrameNs: host.dataset.drawnFrameNs,
      hulls: Number(host.dataset.overlayHulls),
      territoryCells: Number(host.dataset.overlayTerritoryCells),
      influenceCells: Number(host.dataset.overlayInfluenceCells),
      ballState: document.querySelector<HTMLElement>("[data-testid='pitch-frame-summary']")?.textContent?.trim() ?? "",
      pitchDimensionsM: [host.dataset.pitchLengthM, host.dataset.pitchWidthM],
      selection,
      trailsVisible: [...document.querySelectorAll<HTMLButtonElement>("button")]
        .find((button) => button.title?.includes("Trails") || button.innerText.includes("Trails"))
        ?.getAttribute("aria-pressed") ?? null,
      buttonCount: pressed.length,
    };
  });
  expect(snapshot.selection).toContain(player.id);
  await host.screenshot({ path: path.resolve(process.cwd(), `../../output/playwright/res-113/parity-${mode}.png`) });

  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause playback", exact: true })).toBeVisible();
  const beforeForward = await playheadNs(page);
  await expect.poll(async () => (await playheadNs(page))!, { timeout: 5_000 })
    .toBeGreaterThan(beforeForward + 500_000_000n);
  await page.getByRole("button", { name: "Pause playback" }).click();
  const afterForward = (await playheadNs(page))!;
  await expect(host).toHaveAttribute("data-drawn-frame-ns", (await host.getAttribute("data-drawn-frame-ns"))!);

  await page.getByRole("button", { name: "Reverse", exact: true }).click();
  await expect(page.getByRole("button", { name: "Pause playback", exact: true })).toBeVisible();
  const beforeReverse = await playheadNs(page);
  await expect.poll(async () => (await playheadNs(page))!, { timeout: 5_000 })
    .toBeLessThan(beforeReverse - 500_000_000n);
  await page.getByRole("button", { name: "Pause playback" }).click();
  const afterReverse = (await playheadNs(page))!;
  await expectCleanConsole(errors);

  return {
    ...snapshot,
    sourceEvents,
    forwardDeltaNs: (afterForward! - beforeForward!).toString(),
    reverseDeltaNs: (afterReverse - beforeReverse!).toString(),
  };
}

test("real DFL Pixi oracle and R3F renderer agree on Field data, layers, selection and playback", async ({ page }) => {
  const player = await firstTrackedPlayer(page);
  const pixi = await captureRenderer(page, "pixi", player);
  const r3f = await captureRenderer(page, "r3f", player);

  for (const key of ["canonicalTimeNs", "sourceFrameNs", "hulls", "territoryCells", "influenceCells", "ballState", "pitchDimensionsM", "selection", "trailsVisible", "sourceEvents"] as const) {
    expect(r3f[key], key).toEqual(pixi[key]);
  }
  expect(BigInt(pixi.forwardDeltaNs)).toBeGreaterThan(0n);
  expect(BigInt(r3f.forwardDeltaNs)).toBeGreaterThan(0n);
  expect(BigInt(pixi.reverseDeltaNs)).toBeLessThan(0n);
  expect(BigInt(r3f.reverseDeltaNs)).toBeLessThan(0n);
  expect(BigInt(r3f.forwardDeltaNs) - BigInt(pixi.forwardDeltaNs)).toBeLessThan(750_000_000n);
  expect(BigInt(pixi.forwardDeltaNs) - BigInt(r3f.forwardDeltaNs)).toBeLessThan(750_000_000n);
  expect(BigInt(r3f.reverseDeltaNs) - BigInt(pixi.reverseDeltaNs)).toBeLessThan(750_000_000n);
  expect(BigInt(pixi.reverseDeltaNs) - BigInt(r3f.reverseDeltaNs)).toBeLessThan(750_000_000n);

  const receipt = {
    issue: "RES-113",
    rendererModes: { pixi, r3f },
    criteria: ["source frame", "fixed metric dimensions", "hull/territory/influence counts", "player pointer selection", "ball/detection summary", "trail layer", "events in exact window", "forward and reverse canonical time"],
    screenshots: { pixi: "parity-pixi.png", r3f: "parity-r3f.png" },
    visualReviewNote: "Player coordinates and tactical outlines align. Pixi renders a banded surface texture while R3F uses a flat green pitch; review this non-measurement visual difference before retiring the Pixi oracle.",
  };
  await mkdir(path.dirname(path.resolve(process.cwd(), "../../output/playwright/res-113/pixi-parity.json")), { recursive: true });
  await writeFile(path.resolve(process.cwd(), "../../output/playwright/res-113/pixi-parity.json"), JSON.stringify(receipt, null, 2) + "\n");
});
