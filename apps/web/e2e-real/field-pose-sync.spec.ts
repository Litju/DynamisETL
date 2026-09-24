import { expect, test, type Page } from "@playwright/test";

import { SC, expectCleanConsole, measurePlayback, playheadNs, probe, waitForPitch } from "./helpers";

interface StreamAuthority {
  readonly stream_id: string;
  readonly modality: string;
  readonly trial_id: string | null;
  readonly sample_artifact_ids: readonly string[];
  readonly nominal_sampling_rate_hz: number | null;
}

interface SessionAuthority {
  readonly participants: readonly { readonly subject_id: string }[];
  readonly streams: readonly StreamAuthority[];
}

interface PoseObservation {
  readonly entity_id: string;
  readonly first_observed_ns: number;
  readonly last_observed_ns: number;
  readonly observation_count: number;
}

async function matchSubjects(page: Page) {
  const sessionResponse = await page.request.get(
    "/api/catalog/datasets/skillcorner-opendata/sessions/1925299",
  );
  expect(sessionResponse.ok()).toBe(true);
  const session = await sessionResponse.json() as SessionAuthority;
  const tracking = session.streams.find((stream) => stream.stream_id === "tracking-period-1")!;
  const pose = session.streams.find((stream) => stream.stream_id === "pose-period-1")!;
  const participantIds = new Set(session.participants.map((participant) => participant.subject_id));
  const poseResponse = await page.request.get(`/api/artifacts/${pose.sample_artifact_ids[0]}`);
  expect(poseResponse.ok()).toBe(true);
  const artifact = await poseResponse.json() as { readonly entity_observations: readonly PoseObservation[] };
  const windowResponse = await page.request.get(
    `/api/artifacts/${tracking.sample_artifact_ids[0]}/window?from_ns=0&to_ns=0&columns=t_rel_ns%2Cobject_id%2Cobject_type%2Cx_m%2Cy_m&max_points=100`,
  );
  expect(windowResponse.ok()).toBe(true);
  const window = await windowResponse.json() as { readonly rows: readonly { readonly object_id: string; readonly object_type: string }[] };
  const firstFramePlayers = new Set(
    window.rows.filter((row) => row.object_type === "player" || row.object_type === "goalkeeper")
      .map((row) => row.object_id),
  );
  const subjects = artifact.entity_observations
    .filter((observation) => participantIds.has(observation.entity_id) &&
      firstFramePlayers.has(observation.entity_id) && observation.observation_count > 100)
    .sort((left, right) => left.entity_id.localeCompare(right.entity_id));
  expect(subjects.length).toBeGreaterThanOrEqual(2);
  return { tracking, pose, subjects };
}

async function waitForPose(page: Page) {
  await expect(page.getByTestId("matchlab-canvas").locator("canvas")).toBeVisible();
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
}

test("real SkillCorner Field selection preserves time into Pose and both views play the same canonical clock", async ({ page }) => {
  const console = probe(page);
  const { tracking, pose, subjects } = await matchSubjects(page);
  const selected = subjects[0]!;
  const poseRateHz = pose.nominal_sampling_rate_hz ?? 25;
  const trackingRateHz = tracking.nominal_sampling_rate_hz ?? 10;

  await page.goto(`${SC}?view=field&stream=${tracking.stream_id}&t_ns=0`);
  const field = await waitForPitch(page);
  await expect(field).toHaveAttribute("data-drawn-frame-ns", "0");
  await page.getByRole("button", { name: `Select player ${selected.entity_id}`, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`subject=${selected.entity_id}(?:&|$)`));
  await expect(page).toHaveURL(/t_ns=0(?:&|$)/);
  await expect(page.getByTestId("pitch-selection")).toContainText(selected.entity_id);

  await page.getByRole("tab", { name: "pose", exact: true }).click();
  await expect(page).toHaveURL(/view=pose/);
  await waitForPose(page);
  const poseView = page.getByTestId("pose-canvas");
  await expect(poseView).toHaveAttribute("data-selected-player-id", selected.entity_id);
  await expect(poseView).toHaveAttribute("data-canonical-time-ns", "0");
  // The first real observation is 440 ms for this source; field-origin
  // selection keeps time zero and reports Pose absent rather than jumping.
  await expect(poseView).toHaveAttribute("data-pose-availability", "absent");
  expect(await playheadNs(page)).toBe(0n);
  await expect(page.getByTestId("pose-telemetry")).toContainText("First observation");

  await page.getByRole("button", { name: "Play", exact: true }).click();
  const playback = await measurePlayback(page, 1_500);
  await page.getByRole("button", { name: "Pause playback" }).click();
  expect(playback.distinctCanvases).toBe(1);
  const canonicalTimeNs = (await playheadNs(page))!;
  expect(canonicalTimeNs).toBeGreaterThan(1_000_000_000n);
  await expect(poseView).toHaveAttribute("data-canonical-time-ns", canonicalTimeNs.toString());
  const poseFrameNs = BigInt((await poseView.getAttribute("data-source-frame-ns"))!);
  expect(canonicalTimeNs - poseFrameNs).toBeLessThanOrEqual(BigInt(Math.ceil(1.5e9 / poseRateHz)));

  await page.getByRole("tab", { name: "field", exact: true }).click();
  const resumedField = await waitForPitch(page);
  await expect(resumedField).toHaveAttribute("data-selected-player-id", selected.entity_id);
  await expect(resumedField).toHaveAttribute("data-canonical-time-ns", canonicalTimeNs.toString());
  const trackingFrameNs = BigInt((await resumedField.getAttribute("data-drawn-frame-ns"))!);
  expect(canonicalTimeNs - trackingFrameNs).toBeLessThanOrEqual(BigInt(Math.ceil(1.5e9 / trackingRateHz)));
  await expectCleanConsole(console);
});

test("real SkillCorner Pose-origin subject selection updates Field identity and canonical time", async ({ page }) => {
  const console = probe(page);
  const { pose, subjects } = await matchSubjects(page);
  const [from, to] = subjects;
  const targetTimeNs = BigInt(to!.first_observed_ns);

  await page.goto(`${SC}?view=pose&stream=${pose.stream_id}&subject=${from!.entity_id}&t_ns=${from!.first_observed_ns}`);
  await waitForPose(page);
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-selected-player-id", from!.entity_id);
  await page.locator("#pose-subject").selectOption(to!.entity_id);
  await expect(page).toHaveURL(new RegExp(`subject=${to!.entity_id}`));
  await expect(page).toHaveURL(new RegExp(`t_ns=${targetTimeNs}`));
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-canonical-time-ns", targetTimeNs.toString());

  await page.getByRole("tab", { name: "field", exact: true }).click();
  const field = await waitForPitch(page);
  await expect(field).toHaveAttribute("data-selected-player-id", to!.entity_id);
  await expect(field).toHaveAttribute("data-canonical-time-ns", targetTimeNs.toString());
  await expect(page.getByTestId("pitch-selection")).toContainText(to!.entity_id);
  await expectCleanConsole(console);
});

test("real SkillCorner split Field and Pose views share one scissored Canvas and canonical clock", async ({ page }) => {
  const console = probe(page);
  const { tracking, pose, subjects } = await matchSubjects(page);
  const selected = subjects[0]!;
  const poseRateHz = pose.nominal_sampling_rate_hz ?? 25;
  const trackingRateHz = tracking.nominal_sampling_rate_hz ?? 10;
  const initialTimeNs = 1_000_000_000n;

  await page.goto(`${SC}?view=split&stream=${tracking.stream_id}&subject=${selected.entity_id}&t_ns=${initialTimeNs}`);
  const field = await waitForPitch(page);
  await waitForPose(page);
  const poseView = page.getByTestId("pose-canvas");
  await expect(field).toHaveAttribute("data-renderer", "r3f");
  await expect(field).toHaveAttribute("data-canonical-time-ns", initialTimeNs.toString());
  await expect(poseView).toHaveAttribute("data-canonical-time-ns", initialTimeNs.toString());
  await expect(poseView).toHaveAttribute("data-selected-player-id", selected.entity_id);
  await expect(page.getByTestId("matchlab-canvas").locator("canvas")).toHaveCount(1);
  const fieldCameraId = await field.getAttribute("data-view-camera-id");
  const poseCameraId = await poseView.getAttribute("data-view-camera-id");
  expect(fieldCameraId).toBeTruthy();
  expect(poseCameraId).toBeTruthy();
  expect(fieldCameraId).not.toBe(poseCameraId);

  const initialTrackingFrameNs = BigInt((await field.getAttribute("data-drawn-frame-ns"))!);
  const initialPoseFrameNs = BigInt((await poseView.getAttribute("data-source-frame-ns"))!);
  expect(initialTimeNs - initialTrackingFrameNs).toBeLessThanOrEqual(BigInt(Math.ceil(1.5e9 / trackingRateHz)));
  expect(initialTimeNs - initialPoseFrameNs).toBeLessThanOrEqual(BigInt(Math.ceil(1.5e9 / poseRateHz)));

  await page.getByRole("button", { name: "Play", exact: true }).first().click();
  const playback = await measurePlayback(page, 1_000);
  await page.getByRole("button", { name: "Pause playback" }).first().click();
  expect(playback.distinctCanvases).toBe(1);
  const canonicalTimeNs = (await playheadNs(page))!;
  expect(canonicalTimeNs).toBeGreaterThan(initialTimeNs + 500_000_000n);
  await expect(field).toHaveAttribute("data-canonical-time-ns", canonicalTimeNs.toString());
  await expect(poseView).toHaveAttribute("data-canonical-time-ns", canonicalTimeNs.toString());
  await expectCleanConsole(console);
});
