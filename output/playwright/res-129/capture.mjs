import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { gzipSync } from "node:zlib";
const appDir = path.resolve(import.meta.dirname, "../../../apps/web");
const require = createRequire(path.join(appDir, "package.json"));
const { chromium } = require("@playwright/test");

const webBase = "http://127.0.0.1:4174";
const apiBase = "http://127.0.0.1:8000";
const resources = (await (await fetch(`${apiBase}/api/catalog/read-model`)).json()).resources;
const edition = resources.find((item) => item.resource_kind === "competition_edition" && item.sport_id === "football" && item.competition_name === "A-League" && item.edition_label === "2024/2025");
assert.ok(edition, "live RES-125 read model must contain A-League 2024/25");
const matches = resources.filter((item) => item.resource_kind === "contest" && item.edition_id === edition.edition_id);
const readyMatches = matches.filter((item) => item.stages.ready === "ready");
const upstreamOnly = matches.filter((item) => item.stages.ready !== "ready");
const match = readyMatches.find((item) => item.dataset_ids?.includes("skillcorner-opendata") && item.label.startsWith("Brisbane Roar FC"));
assert.ok(match?.session_id, "live read model must contain the ready SkillCorner Brisbane match");
assert.ok(match.routes?.some((route) => route.product === "MatchLab" && route.ready), "match must route to the existing Match World");

const outputRoot = path.resolve(appDir, "../../output/playwright/res-129/final");
await mkdir(outputRoot, { recursive: true });
const browser = await chromium.launch({ headless: true });
const viewport = JSON.parse(process.env.RES129_VIEWPORT ?? '{"label":"1366x768","width":1366,"height":768}');
const context = await browser.newContext({
  viewport: { width: viewport.width, height: viewport.height },
  deviceScaleFactor: 1,
  reducedMotion: "reduce",
});
const page = await context.newPage();
page.setDefaultTimeout(30000);
const requests = [];
const responses = [];
const consoleErrors = [];
page.on("request", (request) => {
  const url = new URL(request.url());
  requests.push({ url: url.href, path: url.pathname + url.search, type: request.resourceType(), method: request.method() });
});
page.on("response", (response) => {
  const headers = response.headers();
  responses.push({
    url: response.url(),
    status: response.status(),
    type: response.request().resourceType(),
    bytes: Number(headers["content-length"] ?? 0),
    contentEncoding: headers["content-encoding"] ?? null,
  });
});
page.on("pageerror", (error) => consoleErrors.push(error.message));
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
await page.route("**/api/**", async (route) => {
  const url = new URL(route.request().url());
  await route.fulfill({
    response: await route.fetch({ url: `${apiBase}${url.pathname}${url.search}` }),
  });
});

const viewportDir = path.join(outputRoot, viewport.label);
await mkdir(viewportDir, { recursive: true });
const steps = [];
let responseMark = 0;
async function capture(name) {
  const file = path.join(viewportDir, `${name}.png`);
  await page.screenshot({ path: file, animations: "disabled" });
  const js = [];
  for (const response of responses.slice(responseMark).filter((item) => item.type === "script")) {
    const asset = new URL(response.url).pathname.split("/").pop();
    const body = await readFile(path.resolve(appDir, "dist", "assets", asset));
    js.push({ file: asset, bytes: body.length, gzipBytes: gzipSync(body).length, status: response.status });
  }
  responseMark = responses.length;
  steps.push({ name, url: page.url(), file, js });
}
const dataNav = page.getByRole("navigation", { name: "Data hierarchy" });

await page.goto(webBase + "/", { waitUntil: "domcontentloaded" });
await page.getByRole("heading", { name: "Research", exact: true }).waitFor({ state: "visible" });
await page.getByText(/25 contests.*48 editions/).waitFor({ state: "visible" });
await capture("01-research-home");

await page.getByRole("link", { name: "Data", exact: true }).click();
await page.getByRole("heading", { name: "Sports", exact: true }).waitFor({ state: "visible" });
await page.getByRole("link", { name: /Human Performance/i }).waitFor({ state: "visible" });
await capture("02-data-browser");

await dataNav.getByRole("link", { name: "Sports", exact: true }).click();
await page.waitForURL((url) => url.searchParams.get("domain") === "sports");
await capture("03-sports");

await dataNav.getByRole("link", { name: /Football/ }).click();
await page.waitForURL((url) => url.searchParams.get("sport") === "football");
await page.getByRole("heading", { name: "Football", exact: true }).waitFor({ state: "visible" });
await capture("04-football");

await page.getByRole("link", { name: /2024\/2025/ }).click();
await page.getByRole("heading", { name: /A-League 2024\/2025/ }).waitFor({ state: "visible" });
await page.getByRole("tab", { name: /Matches 20/ }).waitFor({ state: "visible" });
await capture("05-a-league-2024-25");

const status = page.getByRole("combobox", { name: "Status" });
await status.click();
await page.getByRole("option", { name: "Ready server-side", exact: true }).click();
await page.waitForURL((url) => url.searchParams.get("status") === "ready");
const returnUrl = page.url();
const readyMatchLink = page.getByRole("link", { name: /Open Match World: Brisbane Roar FC 0-1 Perth Glory Football Club/ });
await readyMatchLink.waitFor({ state: "visible" });
await capture("06-ready-skillcorner-match");

const beforeWorldRequests = requests.length;
const beforeWorldScripts = [...new Set(responses.filter((response) => response.type === "script").map((response) => new URL(response.url).pathname.split("/").pop()))];
const heavyChunk = /(echarts|^View-|three|fiber|drei|PoseScene|PitchReplay|MatchLabCanvasRoot)/iu;
const preWorldHeavyScripts = beforeWorldScripts.filter((file) => heavyChunk.test(file));
await readyMatchLink.click();
await page.getByRole("button", { name: "Back", exact: true }).waitFor({ state: "visible" });
await page.getByTestId("matchlab-composition").waitFor({ state: "visible" });
await page.getByText(/29\/29 landmarks/).waitFor({ state: "visible", timeout: 120000 });
await page.waitForTimeout(5000);
const preWorldRequests = requests.slice(0, beforeWorldRequests);
const densePaths = preWorldRequests.filter((request) =>
  /^\/api\/artifacts\/[^/]+\/window$/.test(new URL(request.url).pathname) ||
  /^\/api\/tactical\/series\//.test(new URL(request.url).pathname) ||
  /^\/api\/basketball\/[^/]+\/frames/.test(new URL(request.url).pathname),
);
assert.equal(densePaths.length, 0, "ordinary catalog browsing must not request dense telemetry");
await capture("07-match-world");

await page.getByRole("button", { name: "Back", exact: true }).click();
await page.waitForURL((url) => url.href === returnUrl);
await page.getByRole("tab", { name: /Matches 20/ }).waitFor({ state: "visible" });
await page.getByRole("link", { name: /Open Match World: Brisbane Roar FC 0-1 Perth Glory Football Club/ }).waitFor({ state: "visible" });
await capture("08-back-exact-catalog-context");

await page.getByRole("link", { name: "Research", exact: true }).click();
await page.getByRole("heading", { name: "Continue", exact: true }).waitFor({ state: "visible" });
await page.getByText(/Brisbane Roar FC 0–1 Perth Glory Football Club/).first().waitFor({ state: "visible" });
await capture("09-research-home-recent");

const uniqueScripts = [];
for (const response of new Map(responses.filter((item) => item.type === "script").map((item) => [item.url, item])).values()) {
  const file = new URL(response.url).pathname.split("/").pop();
  const body = await readFile(path.resolve(appDir, "dist", "assets", file));
  uniqueScripts.push({ file, bytes: body.length, gzipBytes: gzipSync(body).length, status: response.status });
}
const apiRequests = requests.filter((request) => new URL(request.url).pathname.startsWith("/api/"));
const denseApiRequests = apiRequests.filter((request) =>
  /^\/api\/artifacts\/[^/]+\/window$/.test(new URL(request.url).pathname) ||
  /^\/api\/tactical\/series\//.test(new URL(request.url).pathname) ||
  /^\/api\/basketball\/[^/]+\/frames/.test(new URL(request.url).pathname),
);
const report = {
  viewport,
  liveCorpus: {
    editionId: edition.edition_id,
    matches: matches.length,
    ready: readyMatches.length,
    upstreamOnly: upstreamOnly.length,
    selected: { label: match.label, datasetId: match.dataset_ids[0], sessionId: match.session_id },
  },
  returnUrl,
  noDenseRequestsBeforeWorld: densePaths.length === 0,
  staticRouteChunksBeforeWorld: { files: beforeWorldScripts, heavy: preWorldHeavyScripts },
  matchWorldChunkFiles: uniqueScripts.map((asset) => asset.file).filter((file) => !beforeWorldScripts.includes(file)),
  steps,
  javascriptAssets: uniqueScripts,
  apiRequestCounts: {
    beforeWorld: preWorldRequests.filter((request) => new URL(request.url).pathname.startsWith("/api/")).length,
    afterWorldTotal: apiRequests.length,
    denseAfterWorld: denseApiRequests.length,
  },
  apiRequests: apiRequests.map((request) => ({ path: request.path, type: request.type })),
  consoleErrors,
};
const manifest = JSON.parse(await readFile(path.resolve(appDir, "dist/.vite/manifest.json"), "utf8"));
function staticImports(key, seen = new Set()) {
  if (seen.has(key) || !manifest[key]) return seen;
  seen.add(key);
  for (const dependency of manifest[key].imports ?? []) staticImports(dependency, seen);
  return seen;
}
const staticRouteAudit = {};
for (const key of ["src/pages/research.tsx", "src/pages/data.tsx", "src/pages/library.tsx"]) {
  const modules = [...staticImports(key)];
  const files = modules.map((module) => manifest[module]?.file).filter((file) => file?.endsWith(".js"));
  staticRouteAudit[key] = { files, heavy: files.filter((file) => heavyChunk.test(path.basename(file))) };
}
report.staticRouteAudit = staticRouteAudit;
await writeFile(path.join(viewportDir, "report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify({
  viewport: report.viewport,
  corpus: report.liveCorpus,
  returnUrl: report.returnUrl,
  noDenseRequestsBeforeWorld: report.noDenseRequestsBeforeWorld,
  beforeWorldApiRequests: report.apiRequestCounts.beforeWorld,
  totalApiRequests: report.apiRequestCounts.afterWorldTotal,
  denseApiRequestsAfterWorld: report.apiRequestCounts.denseAfterWorld,
  staticRouteAudit: Object.fromEntries(Object.entries(report.staticRouteAudit).map(([route, value]) => [route, { staticChunks: value.files.length, heavy: value.heavy }])),
  beforeWorldScripts: { count: beforeWorldScripts.length, heavy: preWorldHeavyScripts },
  matchWorldChunks: report.matchWorldChunkFiles.map((file) => {
    const asset = uniqueScripts.find((item) => item.file === file);
    return { file, bytes: asset?.bytes, gzipBytes: asset?.gzipBytes };
  }),
  steps: report.steps.map(({ name, js }) => ({ name, js: js.map(({ file, bytes, gzipBytes }) => ({ file, bytes, gzipBytes })) })),
  consoleErrors: report.consoleErrors,
}, null, 2));
await context.close();
await browser.close();
