import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { expectCleanConsole, probe, waitForPitch } from "../e2e-real/helpers";

const baseURL = process.env.DYNAMIS_REAL_BASE_URL;
const receiptPath = process.env.DYNAMIS_PREVIEW_ARTIFACT_RECEIPT;
const smokeReceiptPath = process.env.DYNAMIS_PREVIEW_SMOKE_RECEIPT;
const gitSha = process.env.DYNAMIS_CODE_GIT_SHA;
if (!baseURL || !receiptPath || !smokeReceiptPath || !gitSha) {
  throw new Error(
    "Set DYNAMIS_REAL_BASE_URL, DYNAMIS_PREVIEW_ARTIFACT_RECEIPT, DYNAMIS_PREVIEW_SMOKE_RECEIPT, and DYNAMIS_CODE_GIT_SHA",
  );
}
if (!/^[0-9a-f]{40}$/.test(gitSha)) {
  throw new Error("DYNAMIS_CODE_GIT_SHA must be a 40-character lowercase Git SHA");
}
const base = new URL(baseURL);
if (base.protocol !== "https:" || base.pathname !== "/") {
  throw new Error("DYNAMIS_REAL_BASE_URL must be an HTTPS Vercel deployment origin");
}

const receipt = JSON.parse(await readFile(receiptPath, "utf8")) as {
  environment: string;
  objects: Array<{
    dataset_id: string;
    checksum_sha256: string;
    artifact_ids: string[];
  }>;
};
if (receipt.environment !== "preview") {
  throw new Error("Preview smoke requires a Preview artifact receipt");
}
const artifact = receipt.objects.find(
  (item) =>
    item.dataset_id === "dfl-sportec-idsse" &&
    item.checksum_sha256 === "a1150b16850c1606230dfcaa89aa9beec772ff545d469076fde0716cbd4786bc" &&
    item.artifact_ids.includes("tracking-period-1-a1150b16850c"),
);
if (!artifact) throw new Error("Preview has no rights-approved DFL tracking-period-1 Parquet artifact");

const allowlist = JSON.parse(
  await readFile(
    path.resolve(process.cwd(), "../../infra/deploy/production-data-allowlist.json"),
    "utf8",
  ),
) as { datasets: Array<{ dataset_id: string }> };
const allowedIds = new Set(allowlist.datasets.map((item) => item.dataset_id));

test("Vercel Preview API, rights, Private Blob, deep links, and client boundary", async ({ page }) => {
  const console = probe(page);
  const localRequests: string[] = [];
  const apiOrigins: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (["localhost", "127.0.0.1", "::1"].includes(url.hostname)) {
      localRequests.push(url.href);
    }
    if (url.pathname.startsWith("/api/")) apiOrigins.push(url.origin);
  });

  const home = await page.goto("/");
  expect(home?.status()).toBe(200);
  const api = await page.evaluate(async () => {
    const read = async (path: string) => {
      const response = await fetch(path);
      return { status: response.status, body: await response.json() };
    };
    const [health, ready, catalog] = await Promise.all([
      read("/api/health"),
      read("/api/ready"),
      read("/api/catalog/datasets"),
    ]);
    return { health, ready, catalog };
  });
  expect(api.health.status).toBe(200);
  expect(api.ready.status).toBe(200);
  expect(api.catalog.status).toBe(200);

  const datasets = api.catalog.body as Array<{
    dataset_id: string;
    license: {
      status: string;
      identifier: string | null;
      local_only: boolean;
      noncommercial_only: boolean;
      redistribution: string;
    };
  }>;
  expect(datasets.length).toBeGreaterThan(0);
  for (const dataset of datasets) {
    expect(allowedIds.has(dataset.dataset_id), `${dataset.dataset_id} is not allowlisted`).toBe(true);
    expect(dataset.license.status).toBe("declared");
    expect(dataset.license.identifier).toBeTruthy();
    expect(dataset.license.local_only).toBe(false);
    expect(dataset.license.noncommercial_only).toBe(false);
    expect(dataset.license.redistribution).not.toBe("prohibited");
  }

  const restrictedSource = await page.evaluate(async () => {
    const response = await fetch("/api/processing/artifacts?dataset_id=sportsdataverse");
    return { status: response.status, body: await response.json() };
  });
  expect(restrictedSource.status).toBe(451);
  expect(restrictedSource.body.state).toBe("rights_restricted");

  const artifactRead = await page.evaluate(async (artifactId) => {
    const detailResponse = await fetch(`/api/artifacts/${encodeURIComponent(artifactId)}`);
    const detail = await detailResponse.json();
    if (!detailResponse.ok) return { status: detailResponse.status, detail, windowStatus: 0 };
    const from = Number(detail.canonical_time_min_ns);
    const query = new URLSearchParams({
      from_ns: String(from),
      to_ns: String(Math.min(Number(detail.canonical_time_max_ns), from + 1_000_000_000)),
      max_points: "64",
    });
    const windowResponse = await fetch(
      `/api/artifacts/${encodeURIComponent(artifactId)}/window?${query}`,
    );
    return {
      status: detailResponse.status,
      detail,
      windowStatus: windowResponse.status,
      window: await windowResponse.json(),
    };
  }, "tracking-period-1-a1150b16850c");
  expect(artifactRead.status).toBe(200);
  expect(artifactRead.detail.dataset_id).toBe("dfl-sportec-idsse");
  expect(artifactRead.detail.artifact_id).toBe("tracking-period-1-a1150b16850c");
  expect(artifactRead.detail.checksum_sha256).toBe(artifact.checksum_sha256);
  expect(artifactRead.windowStatus).toBe(200);
  expect(artifactRead.window.rows.length).toBeGreaterThan(0);
  expect(JSON.stringify(artifactRead)).not.toMatch(/\.private\.blob\.vercel-storage\.com/i);

  const firstPartyClient = await page.evaluate(async () => {
    const scripts = Array.from(document.scripts)
      .map((script) => script.src)
      .filter((source) => source && new URL(source).origin === window.location.origin);
    const sources = await Promise.all(
      scripts.map(async (source) => (await fetch(source)).text()),
    );
    return `${document.documentElement.outerHTML}\n${sources.join("\n")}`;
  });
  expect(firstPartyClient).not.toMatch(/localhost|127\.0\.0\.1/i);
  expect(firstPartyClient).not.toMatch(
    /POSTGRES_URL|DATABASE_URL|BLOB_READ_WRITE_TOKEN|VERCEL_OIDC_TOKEN|DYNAMIS_MIGRATION_POSTGRES_URL|\.neon\.tech|\.private\.blob\.vercel-storage\.com/i,
  );

  const dataBrowser = await page.goto("/data");
  expect(dataBrowser?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Sports", level: 1 })).toBeVisible();

  const performance = await page.goto("/performance?dataset=white-cmj-acc-grf");
  expect(performance?.status()).toBe(200);
  await expect(
    page.getByRole("heading", { name: "White CMJ accelerometer + vGRF", level: 1 }),
  ).toBeVisible();

  const season = await page.goto("/season");
  expect(season?.status()).toBe(200);
  await expect(page.locator("body")).toContainText(/No season-grain data is materialized\.|Season World/);

  const deepLink =
    process.env.DYNAMIS_SMOKE_DEEP_LINK ??
    "/lab/dfl-sportec-idsse/DFL-MAT-J03WPY?view=field&stream=tracking-period-1&tactical=live";
  const requestedURL = new URL(deepLink, base);
  const deepLinkResponse = await page.goto(requestedURL.href);
  expect(deepLinkResponse?.status()).toBe(200);
  await waitForPitch(page);
  expect(new URL(page.url()).pathname).toBe(requestedURL.pathname);
  const durableURL = page.url();
  await page.reload({ waitUntil: "domcontentloaded" });
  await waitForPitch(page);
  expect(page.url()).toBe(durableURL);

  expect(localRequests).toEqual([]);
  expect(apiOrigins.length).toBeGreaterThan(0);
  expect(apiOrigins.every((origin) => origin === base.origin)).toBe(true);
  await expectCleanConsole(console);

  await mkdir(path.dirname(smokeReceiptPath), { recursive: true });
  await writeFile(
    smokeReceiptPath,
    `${JSON.stringify(
      {
        environment: "preview",
        git_sha: gitSha,
        preview_url: base.origin,
        gates: {
          rights: "passed",
          secrets: "passed",
          private_blob: "passed",
          deep_links: "passed",
          external_smoke: "passed",
        },
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
});
