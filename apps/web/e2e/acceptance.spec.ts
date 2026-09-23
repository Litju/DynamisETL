import { expect, test } from "@playwright/test";

import { installApiMocks } from "./fixtures";

const DEEP_LINK =
  "/lab/skillcorner-opendata/1925299?trial=period-1&subject=SC-P1&view=overview&t_ns=2987480000000";

test.beforeEach(async ({ page }) => {
  await installApiMocks(page);
});

test("1. deep link loads deterministic analytical context and survives reload", async ({ page }) => {
  await page.goto(DEEP_LINK);
  await expect(page.getByText("skillcorner-opendata").first()).toBeVisible();
  await expect(page.getByText("period-1").first()).toBeVisible();
  await expect(page.getByText("SC-P1").first()).toBeVisible();
  await expect(page.getByText("00:49:47.480").first()).toBeVisible();
  await page.reload();
  await expect(page.getByText("00:49:47.480").first()).toBeVisible();
  await expect(page).toHaveURL(/t_ns=2987480000000/);
});

test("1b. individual selection is URL-owned across reload, scrub and history", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=50000000");
  const picker = page.locator("#pose-subject");
  await expect(picker).toHaveValue("SC-P1");
  await picker.selectOption("SC-P2");
  await expect(page).toHaveURL(/subject=SC-P2/);
  await expect(page).toHaveURL(/t_ns=12000000000/);
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/subject=SC-P2/);
  await page.reload();
  await expect(page).toHaveURL(/subject=SC-P2/);
  await page.goBack();
  await expect(page).toHaveURL(/subject=SC-P1/);
  await page.goForward();
  await expect(page).toHaveURL(/subject=SC-P2/);
});

test("1e. all-subject Pose mode uses one fixed world without entity scoping", async ({ page }) => {
  const poseWindowRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/artifacts/pose-sample/window")) {
      poseWindowRequests.push(request.url());
    }
  });
  await page.goto(
    "/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=12000000000",
  );
  const toggle = page.getByTestId("pose-all-subjects-toggle");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  const requestsBeforeToggle = poseWindowRequests.length;
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("all subjects · fixed camera (2)")).toBeVisible();
  await expect(page.getByText(/2 subjects share one source-coordinate world/)).toBeVisible();
  expect(poseWindowRequests.slice(requestsBeforeToggle).some((url) => !url.includes("entity_id="))).toBe(true);
});

test("1c. Pose playback advances both the playhead and rendered scene", async ({ page }) => {
  await page.goto(
    "/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=0",
  );
  await expect(page.getByTestId("pose-canvas")).toBeVisible();
  const playhead = page.getByLabel("Transport and timeline").locator(".t-value").first();
  const beforeTime = await playhead.innerText();
  const before = await page.screenshot();
  await page.getByRole("button", { name: "Play" }).click();
  await expect.poll(() => playhead.innerText()).not.toBe(beforeTime);
  const afterTime = await playhead.innerText();
  await expect(page.getByTestId("pose-canvas")).toBeVisible();
  const after = await page.screenshot();
  expect(afterTime).not.toBe(beforeTime);
  expect(after.equals(before)).toBe(false);
});

test("1d. Pose telemetry lists every provider landmark in the inspector", async ({ page }) => {
  await page.goto(
    "/lab/skillcorner-opendata/1925299?stream=pose-1&subject=SC-P1&view=pose&t_ns=0",
  );
  const telemetry = page.getByTestId("pose-telemetry");
  await expect(telemetry).toBeVisible();
  await expect(page.locator("#inspector").getByTestId("pose-telemetry")).toBeVisible();
  expect(await page.locator("#explorer [data-testid=pose-telemetry]").count()).toBe(0);
  await expect(telemetry.getByText("29 observed · 0 unavailable")).toBeVisible();
  expect(await telemetry.locator(".grid").count()).toBe(30); // column header + 29 landmarks
  await expect(telemetry.getByText("nose")).toBeVisible();
  await expect(telemetry.getByText("lSmallToe")).toBeVisible();
  await expect(telemetry.getByText("rPinky")).toBeVisible();
});

test("2. selecting a player on the pitch updates the durable subject context", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field");
  const host = page.getByTestId("pitch-canvas");
  await expect(host).toBeVisible();
  await expect(page.getByText(/players · .* extrapolated/)).toBeVisible();
  const canvas = host.locator("canvas");
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  const scale = Math.min(box.width / 120, box.height / 80);
  // p1 sits at (-5 m, 2 m) with the pitch origin at the canvas centre.
  await page.mouse.click(box.x + box.width / 2 - 5 * scale, box.y + box.height / 2 - 2 * scale);
  await expect(page).toHaveURL(/subject=p1/);
  await expect(page.getByText(/p1 · player/)).toBeVisible();
  await expect(page.getByText(/detected$|extrapolated$/).last()).toBeVisible();
});

test("2b. field uses the Tactical Analysis pane with explicit unavailable states", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=tracking-1&view=field&t_ns=0");
  const pane = page.getByRole("region", { name: "Tactical Analysis" });
  await expect(pane).toBeVisible();
  await expect(pane.getByRole("tab", { name: "Live" })).toBeVisible();
  await expect(pane.getByRole("tab", { name: "Shape" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Inspector" })).toHaveCount(0);
  await pane.getByRole("tab", { name: "Shape" }).click();
  await expect(pane.getByText("Unavailable for this source").last()).toBeVisible();
});

test("3/4. committed time propagates from the keyboard to the transport and pose view", async ({
  page,
}) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=tracking-1&view=signals&t_ns=50000000");
  await expect(page.getByText(/json transport/)).toBeVisible();
  await expect(page.getByTestId("uplot")).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/t_ns=/);
  const committed = page.getByText(/^committed$/).locator("xpath=following-sibling::span");
  const committedBefore = await committed.first().textContent();
  expect(committedBefore).not.toBe("—");
  // The same committed time governs the 3D view: it loads with the URL state and
  // the transport reports the identical committed clock.
  const tNs = new URL(page.url()).searchParams.get("t_ns");
  await page.goto(
    `/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=${tNs ?? "50000000"}`,
  );
  await expect(page.getByText(/local analytical frame/)).toBeVisible();
  await expect(committed.first()).toHaveText(committedBefore ?? "");
});

test("5. selecting a landmark shows coordinates, error radius and declared overlays", async ({
  page,
}) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=pose-1&view=pose&t_ns=0");
  await expect(page.getByText(/local analytical frame · Z is player-centroid-relative/)).toBeVisible();
  await expect(
    page.getByText(/1 segment\(s\), 1 angle\(s\) from processor parameters/),
  ).toBeVisible();
  await page.getByRole("button", { name: "lKnee" }).click();
  await expect(page.getByText("selected landmark")).toBeVisible();
  await expect(page.getByText(/provider p90 predicted error radius 0.0400 m/).first()).toBeVisible();
  await expect(page.getByText(/z -0.850 m/)).toBeVisible();
});

test("6. provenance opens the exact algorithm/run/input lineage", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?view=overview&t_ns=50000000");
  await page.getByText("pose.angular_rom.left_knee").first().click();
  const inspector = page.getByRole("region", { name: "Inspector" });
  await inspector.getByRole("tab", { name: "Provenance" }).click();
  const flow = page.getByTestId("lineage-flow");
  await expect(flow.getByText("run-pose")).toBeVisible();
  await expect(flow.getByText(/Translation-invariant pose kinematics@1\.0\.0/)).toBeVisible();
  await expect(flow.getByText("gold_row").first()).toBeVisible();
  // The minimap overlays the pane corner; dispatch the activation on the node
  // wrapper so the assertion targets the lineage interaction, not pane geometry.
  await page.locator('.react-flow__node[data-id="run:run-pose"]').dispatchEvent("click");
  await expect(page.getByText(/processing_run details/)).toBeVisible();
  await expect(page.getByText(/code_git_sha/)).toBeVisible();
});

test("7. license and quality context are visible next to results", async ({ page }) => {
  await page.goto("/quality");
  await expect(page.getByText("CC BY 4.0").first()).toBeVisible();
  await expect(page.getByText("conditional").first()).toBeVisible();
  await expect(page.getByText("tracking.ball_gap")).toBeVisible();
  await expect(page.getByText(/sample 12/)).toBeVisible();
});

test("8. a stream that is not part of the session is never cross-synchronized", async ({ page }) => {
  await page.goto("/lab/skillcorner-opendata/1925299?stream=other-stream&view=signals");
  await expect(page.getByText("Stream is not part of this session.")).toBeVisible();
});

test("9. compare preserves dataset/subject identity boundaries", async ({ page }) => {
  await page.goto("/compare?metric=pose.angular_rom.left_knee");
  await expect(page.getByText("skillcorner-opendata").first()).toBeVisible();
  await expect(
    page
      .getByText(/no observation is paired across groups/)
      .first(),
  ).toBeVisible();
  await expect(page.getByText(/pipeline-derived/).first()).toBeVisible();
});

test("10. methodology page renders the selected result lineage from a deep link", async ({
  page,
}) => {
  await page.goto("/methods?metric=pose.angular_rom.left_knee&result=dm-pose-rom");
  await expect(page.getByText("Selected result lineage")).toBeVisible();
  await expect(page.getByText("run-pose")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Range of motion for angle left_knee" })).toBeVisible();
});
