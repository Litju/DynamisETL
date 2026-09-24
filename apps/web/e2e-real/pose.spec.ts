import { expect, test, type Page } from "@playwright/test";

import { SC, evidence, expectCleanConsole, measurePlayback, playheadNs, probe } from "./helpers";

/**
 * RES-112 real-data Pose acceptance against the live API (no interception).
 * Expected targets come from the served artifact's own observation authority.
 */
const STREAM = "pose-period-1";
const POSE = `${SC}?view=pose&stream=${STREAM}`;

interface Observation {
  readonly entity_id: string;
  readonly first_observed_ns: number;
  readonly last_observed_ns: number;
  readonly observation_count: number;
}

async function observations(page: Page): Promise<Observation[]> {
  const session = await (await page.request.get("/api/catalog/datasets/skillcorner-opendata/sessions/1925299")).json();
  const stream = session.streams.find((item: { stream_id: string }) => item.stream_id === STREAM);
  const artifact = await (await page.request.get(`/api/artifacts/${stream.sample_artifact_ids[0]}`)).json();
  return artifact.entity_observations as Observation[];
}

async function waitForPose(page: Page) {
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
}

test("opens on the selected subject's first observation and every read-out agrees", async ({ page }) => {
  const console = probe(page);
  const observed = await observations(page);
  await page.goto(POSE);
  await waitForPose(page);
  await expect(page).toHaveURL(/subject=\d+/);
  const subject = new URL(page.url()).searchParams.get("subject")!;
  const first = observed.find((item) => item.entity_id === subject)!;
  await expect(page).toHaveURL(new RegExp(`t_ns=${first.first_observed_ns}`));
  expect(await playheadNs(page)).toBe(BigInt(first.first_observed_ns));
  const telemetry = page.getByTestId("pose-telemetry");
  await expect(telemetry).toContainText(subject);
  await expect(telemetry).toContainText(/\d+ observed · \d+ unavailable/);
  await evidence(page, "pose-sc-body-local");
  await expectCleanConsole(console);
});

test("switching subject after >10 s lands on an exact observation and retires the old subject", async ({ page }) => {
  const console = probe(page);
  const observed = await observations(page);
  const [from, to] = observed
    .filter((item) => item.observation_count > 500)
    .sort((left, right) => left.first_observed_ns - right.first_observed_ns)
    .slice(0, 2)
    .map((item) => item.entity_id);
  const fromObservation = observed.find((item) => item.entity_id === from)!;
  const start = Math.max(fromObservation.first_observed_ns, 12_000_000_000);
  await page.goto(`${POSE}&subject=${from}&t_ns=${start}`);
  await waitForPose(page);
  const windowRequests: string[] = [];
  let switched = false;
  page.on("request", (request) => {
    if (!request.url().includes("/window")) return;
    const entity = new URL(request.url()).searchParams.get("entity_id");
    if (entity === to) switched = true;
    if (switched && entity === from) windowRequests.push(request.url());
  });
  await page.locator("#pose-subject").selectOption(to!);
  await expect(page).toHaveURL(new RegExp(`subject=${to}`));
  const target = observed.find((item) => item.entity_id === to)!;
  await expect(page).toHaveURL(new RegExp(`t_ns=${target.first_observed_ns}`));
  await expect(page.getByTestId("pose-telemetry")).toContainText(to!);
  await expect(page.getByTestId("pose-telemetry")).toContainText(/\d+ observed · \d+ unavailable/);
  expect(windowRequests).toEqual([]);

  // History and reload restore the exact subject/time transaction.
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`subject=${from}`));
  await page.goForward();
  await expect(page).toHaveURL(new RegExp(`subject=${to}.*t_ns=${target.first_observed_ns}|t_ns=${target.first_observed_ns}.*subject=${to}`));
  await page.reload();
  await waitForPose(page);
  await expect(page.getByTestId("pose-telemetry")).toContainText(to!);
  await expectCleanConsole(console);
});

test("switching while playing stops playback explicitly (RES-109 §12)", async ({ page }) => {
  const console = probe(page);
  const observed = await observations(page);
  const subjects = observed.filter((item) => item.observation_count > 500).map((item) => item.entity_id);
  await page.goto(`${POSE}&subject=${subjects[0]}`);
  await waitForPose(page);
  await page.getByRole("button", { name: "Play" }).click();
  await page.waitForTimeout(1_500);
  await page.locator("#pose-subject").selectOption(subjects[1]!);
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible();
  await expect(page.getByText("Playback paused for the subject switch — press Play to continue.")).toBeVisible();
  await expect(page.getByTestId("pose-telemetry")).toContainText(subjects[1]!);
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByText("Playback paused for the subject switch — press Play to continue.")).toHaveCount(0);
  await page.getByRole("button", { name: "Pause playback" }).click();
  await expectCleanConsole(console);
});

test("long playback crosses chunks with one renderer and no console errors", async ({ page }) => {
  const console = probe(page);
  await page.goto(POSE);
  await waitForPose(page);
  const before = (await playheadNs(page))!;
  await page.getByLabel("Playback rate").selectOption("4");
  await page.getByRole("button", { name: "Play" }).click();
  const playback = await measurePlayback(page, 9_000);
  await page.getByRole("button", { name: "Pause playback" }).click({ timeout: 3_000 }).catch(() => undefined);
  const after = (await playheadNs(page))!;
  expect(after - before).toBeGreaterThan(25_000_000_000n);
  expect(playback.distinctCanvases).toBe(1);
  await expect(page.getByTestId("pose-telemetry")).toContainText(/\d+ observed · \d+ unavailable/);
  await expectCleanConsole(console);
});

test("frames, scope, camera ownership and layers stay consistent", async ({ page }) => {
  const console = probe(page);
  await page.goto(POSE);
  await waitForPose(page);
  const bodyLocal = page.getByTestId("pose-body-local-mode");
  const world = page.getByTestId("pose-match-world-mode");
  const all = page.getByTestId("pose-all-subjects-toggle");
  await expect(bodyLocal).toHaveAttribute("aria-pressed", "true");
  await world.click();
  await expect(world).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "follow-subject" })).toHaveAttribute("aria-pressed", "true");
  // Manual ownership: dragging the canvas hands the camera to the reader.
  const canvas = page.getByTestId("pose-canvas").locator("canvas");
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 20, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "manual" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("pose-camera-ownership")).toContainText("Manual");
  await all.click();
  await expect(all).toHaveAttribute("aria-pressed", "true");
  await expect(bodyLocal).toBeDisabled();
  await expect(page.getByRole("button", { name: "all-subjects" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText(/all subjects · fixed camera \(\d+\)/)).toBeVisible();
  await page.waitForTimeout(2_000);
  await evidence(page, "pose-sc-all-subjects");
  await page.getByRole("button", { name: "follow-subject" }).click();
  await expect(all).toHaveAttribute("aria-pressed", "false");
  await expect(world).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("pose-camera-reset").click();
  await expect(bodyLocal).toHaveAttribute("aria-pressed", "true");
  const radius = page.getByRole("switch", { name: "p90 error radius (provider)" });
  await expect(radius).toHaveAttribute("aria-checked", "false");
  await radius.click();
  await expect(radius).toHaveAttribute("aria-checked", "true");
  const skeleton = page.getByRole("switch", { name: "skeleton connections (provider)" });
  await skeleton.click();
  await expect(skeleton).toHaveAttribute("aria-checked", "false");
  await expectCleanConsole(console);
});
