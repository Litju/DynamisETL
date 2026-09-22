import { readFile, writeFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { installApiMocks, SESSION } from "./fixtures";

interface LocalPoseFixture {
  readonly source_path: string;
  readonly source_sha256: string;
  readonly artifact: {
    readonly artifact_id: string;
    readonly canonical_time_min_ns: number;
    readonly canonical_time_max_ns: number;
    readonly entity_ids: string[];
    readonly entity_observations: Array<{
      readonly entity_id: string;
      readonly first_observed_ns: number;
      readonly last_observed_ns: number;
      readonly observation_count: number;
    }>;
    readonly [key: string]: unknown;
  };
  readonly columns: string[];
  readonly rows: Array<Record<string, unknown>>;
}

const fixturePath = process.env.RES109_LOCAL_POSE_FIXTURE;

test("RES-109 §12 switches between real local Pose subjects from a >10 s playhead", async ({ page }) => {
  test.skip(!fixturePath, "Set RES109_LOCAL_POSE_FIXTURE from prepare-res109-real-pose.py for the local data receipt.");
  const fixture = JSON.parse(await readFile(fixturePath!, "utf8")) as LocalPoseFixture;
  const artifact = fixture.artifact;
  const requests: Array<{
    entityId: string | null;
    fromNs: number;
    toNs: number;
    returnedRows: number;
  }> = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await installApiMocks(page);

  const session = structuredClone(SESSION);
  const poseStream = session.streams.find((stream) => stream.modality === "pose");
  if (!poseStream) throw new Error("Pose stream is missing from the local session fixture");
  poseStream.sample_artifact_ids = [artifact.artifact_id];
  poseStream.sample_row_count = Number(artifact.row_count);
  const artifactPath = `/api/artifacts/${artifact.artifact_id}`;

  await page.route((url) => url.pathname === "/api/catalog/datasets/skillcorner-opendata/sessions/1925299", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session) });
  });
  await page.route((url) => url.pathname === artifactPath, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(artifact) });
  });
  await page.route((url) => url.pathname === `${artifactPath}/observations`, async (route) => {
    const fromNs = url.searchParams.has("from_ns") ? Number(url.searchParams.get("from_ns")) : Number.NEGATIVE_INFINITY;
    const toNs = url.searchParams.has("to_ns") ? Number(url.searchParams.get("to_ns")) : Number.POSITIVE_INFINITY;
    const observations = artifact.entity_observations.filter((item) =>
      item.last_observed_ns >= fromNs && item.first_observed_ns <= toNs,
    );
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(observations) });
  });
  await page.route((url) => url.pathname === `${artifactPath}/window`, async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("format") === "arrow") {
      await route.fulfill({ status: 415, contentType: "application/json", body: JSON.stringify({ detail: "Arrow fixture transport unavailable" }) });
      return;
    }
    const fromNs = url.searchParams.has("from_ns") ? Number(url.searchParams.get("from_ns")) : artifact.canonical_time_min_ns;
    const toNs = url.searchParams.has("to_ns") ? Number(url.searchParams.get("to_ns")) : artifact.canonical_time_max_ns;
    const entityId = url.searchParams.get("entity_id");
    const rows = fixture.rows.filter((row) => {
      const time = Number(row.t_rel_ns);
      return time >= fromNs && time <= toNs && (entityId === null || String(row.subject_id) === entityId);
    });
    requests.push({ entityId, fromNs, toNs, returnedRows: rows.length });
    const body = {
      meta: {
        artifact,
        from_ns: fromNs,
        to_ns: toNs,
        columns: fixture.columns,
        source_rows: rows.length,
        returned_rows: rows.length,
        canonical_time_min_ns: artifact.canonical_time_min_ns,
        canonical_time_max_ns: artifact.canonical_time_max_ns,
        reduction: null,
        units: { x_m: "m", y_m: "m", z_m: "m", error_m: "m" },
        coordinate_frame_id: "skillcorner-pose-hybrid-m",
        measurement_class: "MODEL_ESTIMATED",
        display_note: "Exact canonical samples from the local SkillCorner Parquet artifact.",
      },
      rows,
    };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  const firstSubject = "11897";
  const targetSubject = "50999";
  const target = artifact.entity_observations.find((item) => item.entity_id === targetSubject);
  expect(target).toBeDefined();
  expect(target!.first_observed_ns).toBeGreaterThan(10_000_000_000);
  await page.goto(`/lab/skillcorner-opendata/1925299?stream=pose-1&subject=${firstSubject}&trial=period_1&view=pose&t_ns=17417738000`);
  await expect(page.getByTestId("pose-canvas").locator("canvas")).toBeVisible();
  await expect(page.getByTestId("pose-telemetry")).toContainText(firstSubject);
  await page.locator("#pose-subject").selectOption(targetSubject);
  await expect(page).toHaveURL(new RegExp(`subject=${targetSubject}`));
  await expect(page).toHaveURL(new RegExp(`t_ns=${target!.first_observed_ns}`));
  await expect(page.getByTestId("pose-telemetry").getByText(/\d+ observed · \d+ unavailable/)).toBeVisible();
  const targetRequest = requests.find((request) =>
    request.entityId === targetSubject && request.fromNs <= target!.first_observed_ns &&
    request.toNs >= target!.first_observed_ns && request.returnedRows > 0,
  );
  expect(targetRequest).toBeDefined();
  expect(errors).toEqual([]);

  const resultPath = process.env.RES109_LOCAL_POSE_RESULT;
  if (resultPath) {
    await writeFile(resultPath, JSON.stringify({
      schema_version: "res109-local-pose-subject-switch-1",
      source_path: fixture.source_path,
      source_sha256: fixture.source_sha256,
      artifact_id: artifact.artifact_id,
      switched_from_subject: firstSubject,
      switched_from_ns: 17_417_738_000,
      switched_to_subject: targetSubject,
      first_observed_ns: target!.first_observed_ns,
      exact_request: targetRequest,
      page_errors: errors,
    }, null, 2) + "\n", "utf8");
  }
});
