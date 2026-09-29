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
const perthId = "team-6db2746c59daa23a45580196";
const bugarijaId = "skillcorner-opendata/966112";
const taggartId = "skillcorner-opendata/211";

const gameEditions = await (await fetch(`${apiBase}/api/games/editions`)).json();
const acbEdition = gameEditions.find((item) => item.dataset_id === "skillcorner-basketball-opendata");
const nbaEdition = gameEditions.find((item) => item.league_id === "nba");
assert.ok(acbEdition && nbaEdition, "live Game World must contain the ACB and NBA editions");
const acbGames = await (await fetch(`${apiBase}/api/games?edition_id=${encodeURIComponent(acbEdition.edition_id)}&limit=1000&offset=0`)).json();
const acbGame = acbGames.rows.find((item) => item.provider_game_id === "114243");
assert.ok(acbGame?.contest_id, "live ACB data must contain the accepted basketball spatial game");
const basketballContest = resources.find((item) => item.resource_kind === "contest" && item.external_ids?.includes("114243"));
assert.ok(basketballContest?.contest_id, "live catalog must contain the ACB tracking contest");
const nbaPage0 = await (await fetch(`${apiBase}/api/games?edition_id=${encodeURIComponent(nbaEdition.edition_id)}&limit=1000&offset=0`)).json();
let nbaGame = nbaPage0.rows.find((item) => item.provider_game_id === "401809243");
for (let offset = 1000; !nbaGame && offset < nbaPage0.total; offset += 1000) {
  const nextPage = await (await fetch(`${apiBase}/api/games?edition_id=${encodeURIComponent(nbaEdition.edition_id)}&limit=1000&offset=${offset}`)).json();
  nbaGame = nextPage.rows.find((item) => item.provider_game_id === "401809243");
}
assert.ok(nbaGame?.contest_id, "live NBA data must contain the accepted local-only rights example");

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
let unavailableCatalogReadModel = false;
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
  if (message.type() === "error" && !/server responded with a status of (?:404|451|503)\b/u.test(message.text())) {
    consoleErrors.push(message.text());
  }
});
await page.route("**/api/**", async (route) => {
  const url = new URL(route.request().url());
  if (unavailableCatalogReadModel && url.pathname === "/api/catalog/read-model") {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "The catalog service is temporarily unavailable." }),
    });
    return;
  }
  await route.fulfill({
    response: await route.fetch({ url: `${apiBase}${url.pathname}${url.search}` }),
  });
});

const viewportDir = path.join(outputRoot, viewport.label);
await mkdir(viewportDir, { recursive: true });
const steps = [];
let responseMark = 0;
async function capture(name, metadata = {}) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  assert.equal(overflow, false, `${name} has horizontal overflow at ${viewport.label}`);
  const file = path.join(viewportDir, `${name}.png`);
  await page.screenshot({ path: file, animations: "disabled" });
  const js = [];
  for (const response of responses.slice(responseMark).filter((item) => item.type === "script")) {
    const asset = new URL(response.url).pathname.split("/").pop();
    const body = await readFile(path.resolve(appDir, "dist", "assets", asset));
    js.push({ file: asset, bytes: body.length, gzipBytes: gzipSync(body).length, status: response.status });
  }
  const scriptTimings = await page.evaluate(() => performance.getEntriesByType("resource")
    .filter((entry) => entry.initiatorType === "script" && /\.js(?:\?|$)/u.test(entry.name))
    .map((entry) => ({
      file: new URL(entry.name).pathname.split("/").at(-1),
      startMs: Math.round(entry.startTime * 100) / 100,
      responseEndMs: Math.round(entry.responseEnd * 100) / 100,
      durationMs: Math.round(entry.duration * 100) / 100,
      transferBytes: entry.transferSize || null,
      encodedBytes: entry.encodedBodySize || null,
    })));
  responseMark = responses.length;
  steps.push({ name, url: page.url(), file, js, scriptTimings, ...metadata });
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

await page.goto(`${webBase}/data?domain=human`);
await page.getByRole("heading", { name: "Human Performance", exact: true }).waitFor({ state: "visible" });
await capture("02-human-performance");

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
const worldNavigationStartedAt = await page.evaluate(() => performance.now());
await readyMatchLink.click();
await page.getByRole("button", { name: "Back", exact: true }).waitFor({ state: "visible" });
await page.getByTestId("matchlab-composition").waitFor({ state: "visible" });
await page.getByText(/29\/29 landmarks/).waitFor({ state: "visible", timeout: 120000 });
await page.locator('[data-testid="pitch-canvas"][data-renderer-ready="true"]').waitFor({ timeout: 120000 });
await page.locator('[data-testid="pose-canvas"][data-renderer-ready="true"]').waitFor({ timeout: 120000 });
const worldUsefulRenderMs = await page.evaluate((startedAt) => Math.round((performance.now() - startedAt) * 100) / 100, worldNavigationStartedAt);
await page.waitForTimeout(5000);
const preWorldRequests = requests.slice(0, beforeWorldRequests);
const initialWorldRequests = requests.slice(beforeWorldRequests);
const densePaths = preWorldRequests.filter((request) =>
  /^\/api\/artifacts\/[^/]+\/window$/.test(new URL(request.url).pathname) ||
  /^\/api\/tactical\/series\//.test(new URL(request.url).pathname) ||
  /^\/api\/basketball\/[^/]+\/frames/.test(new URL(request.url).pathname),
);
assert.equal(densePaths.length, 0, "ordinary catalog browsing must not request dense telemetry");
await capture("07-match-world", { usefulWorldRenderMs: worldUsefulRenderMs });

await page.getByRole("button", { name: "Back", exact: true }).click();
await page.waitForURL((url) => url.href === returnUrl);
await page.getByRole("tab", { name: /Matches 20/ }).waitFor({ state: "visible" });
await page.getByRole("link", { name: /Open Match World: Brisbane Roar FC 0-1 Perth Glory Football Club/ }).waitFor({ state: "visible" });
await capture("08-back-exact-catalog-context");

await page.getByRole("link", { name: "Research", exact: true }).click();
await page.getByRole("heading", { name: "Continue", exact: true }).waitFor({ state: "visible" });
await page.getByText(/Brisbane Roar FC 0–1 Perth Glory Football Club/).first().waitFor({ state: "visible" });
await capture("09-research-home-recent");

await page.goto(`${webBase}/lab`);
await page.getByTestId("match-navigator").waitFor({ state: "visible" });
await capture("06-match-navigator");

await page.goto(`${webBase}/data/edition/${encodeURIComponent(edition.edition_id)}?tab=teams`);
await page.getByRole("tab", { name: /Teams/ }).waitFor({ state: "visible" });
await capture("10-a-league-teams");

await page.goto(`${webBase}/data/edition/${encodeURIComponent(edition.edition_id)}?tab=players`);
await page.getByRole("tab", { name: /Players/ }).waitFor({ state: "visible" });
await capture("11-a-league-players");

await page.goto(`${webBase}/data/edition/${encodeURIComponent(edition.edition_id)}?tab=season`);
await page.getByText("Metric families", { exact: true }).waitFor({ state: "visible" });
await capture("12-a-league-season-data");

await page.goto(`${webBase}/data/team/${perthId}?edition=${encodeURIComponent(edition.edition_id)}`);
await page.getByRole("heading", { name: "Perth Glory Football Club", exact: true }).waitFor({ state: "visible" });
await page.getByText(/registered contests ready/).waitFor({ state: "visible" });
await capture("13-team-perth-glory");

await page.goto(`${webBase}/data/player/${encodeURIComponent(bugarijaId)}?edition=${encodeURIComponent(edition.edition_id)}`);
await page.getByRole("heading", { name: "Adam Bugarija", exact: true }).waitFor({ state: "visible" });
await page.getByText("Pose available", { exact: true }).waitFor({ state: "visible" });
await capture("14-player-adam-bugarija");

await page.goto(`${webBase}/data/player/${encodeURIComponent(taggartId)}?edition=${encodeURIComponent(edition.edition_id)}`);
await page.getByRole("heading", { name: "Adam Taggart", exact: true }).waitFor({ state: "visible" });
await page.getByText(/No materialized contest proves this player's participation/).waitFor({ state: "visible" });
await capture("15-player-adam-taggart-unlinked");

await page.goto(`${webBase}/season?edition=${encodeURIComponent(edition.edition_id)}&family=physical&team=${perthId}&player=${encodeURIComponent(bugarijaId)}`);
await page.locator('[data-renderer="echarts"]').first().waitFor({ state: "attached", timeout: 120000 });
await page.waitForFunction(() => document.querySelector('[data-renderer="echarts"]')?.getAttribute("data-renderer-ready") === "true", null, { timeout: 120000 });
await capture("16-season-bugarija-match-linkage");

await page.goto(`${webBase}/games?edition=${encodeURIComponent(acbEdition.edition_id)}&game=${encodeURIComponent(acbGame.contest_id)}&offset=0`);
await page.getByRole("heading", { name: "Basketball game", exact: true }).waitFor({ state: "visible" });
await page.getByTestId("gamelab").waitFor({ state: "visible" });
await page.getByRole("table", { name: "ACB contests" }).getByRole("row").filter({ hasText: "BAXI Manresa" }).waitFor({ state: "visible" });
await capture("18-game-world");

await page.goto(`${webBase}/basketball?contest=${encodeURIComponent(basketballContest.contest_id)}`);
await page.getByTestId("basketball-court").waitFor({ state: "visible" });
await page.getByRole("slider", { name: "Frame timeline" }).waitFor({ state: "visible" });
await page.locator('[data-testid="basketball-court"][data-frame-idx]').waitFor({ state: "visible" });
await capture("19-basketball-spatial");

await page.goto(`${webBase}/performance?dataset=white-cmj-acc-grf&session=white-s000`);
await page.getByRole("heading", { name: "White CMJ accelerometer + vGRF", exact: true }).waitFor({ state: "visible" });
await page.getByRole("heading", { name: "white-s000", exact: true }).waitFor({ state: "visible" });
await page.getByRole("listbox", { name: "Sessions" }).getByRole("option", { name: /white-s000/ }).waitFor({ state: "visible" });
await page.getByRole("link", { name: "Open first trial" }).waitFor({ state: "visible" });
await capture("20-performance-world");

await page.goto(`${webBase}/performance?dataset=gymaware-landmine-vision&session=session-ga-p001`);
await page.getByRole("heading", { name: "GymAware landmine press + vision agreement", exact: true }).waitFor({ state: "visible" });
await page.getByRole("heading", { name: "session-ga-p001", exact: true }).waitFor({ state: "visible" });
await page.locator('[data-state="upstream"]').getByText("This session is available upstream, not materialized locally.").waitFor({ state: "visible" });
await page.getByText("ga-t001-r01", { exact: true }).waitFor({ state: "visible" });
assert.equal(await page.getByRole("link", { name: "Open first trial" }).count(), 0);
await capture("17-gymaware-upstream-only-session");

await page.goto(`${webBase}/library`);
await page.getByRole("heading", { name: "Library", exact: true }).waitFor({ state: "visible" });
await page.getByRole("link", { name: "Browse pose definitions", exact: true }).waitFor({ state: "visible" });
await capture("21-library-evidence");

await page.goto(`${webBase}/data/edition/${encodeURIComponent(edition.edition_id)}?status=upstream`);
const prepareButton = page.getByRole("button", { name: /^Prepare .* locally$/u }).first();
await prepareButton.waitFor({ state: "visible" });
await prepareButton.click();
await page.getByRole("dialog").waitFor({ state: "visible" });
await page.getByText("Deterministic preparation", { exact: true }).waitFor({ state: "visible" });
await page.getByText("Declared · not acquired", { exact: true }).first().waitFor({ state: "visible" });
await capture("22-prepare");
if (viewport.height <= 768) {
  const scrolled = await page.getByRole("dialog").evaluate((dialog) => {
    let node = dialog.parentElement;
    while (node && node !== document.body) {
      const overflowY = getComputedStyle(node).overflowY;
      if ((overflowY === "auto" || overflowY === "scroll") && node.scrollHeight > node.clientHeight + 8) {
        node.scrollTop = node.scrollHeight;
        return true;
      }
      node = node.parentElement;
    }
    return false;
  });
  assert.equal(scrolled, true, "Prepare dialog should remain reachable by scrolling at compact workstation height");
  await capture("22-prepare-scroll");
}
await page.getByRole("button", { name: "Close" }).click();

const rightsGamePath = `/api/games/${nbaGame.contest_id}`;
const rejectRightsRestrictedPayload = (route) => route.fulfill({
  status: 451,
  contentType: "application/json",
  body: JSON.stringify({ detail: "This local-only source is blocked in public exposure.", state: "rights_restricted" }),
});
await page.route((url) => new URL(url).pathname === `${rightsGamePath}/plays`, rejectRightsRestrictedPayload);
await page.route((url) => new URL(url).pathname === `${rightsGamePath}/box`, rejectRightsRestrictedPayload);
await page.goto(`${webBase}/games?edition=${encodeURIComponent(nbaEdition.edition_id)}&game=${encodeURIComponent(nbaGame.contest_id)}`);
await page.getByLabel("Local-only source rights").waitFor({ state: "visible" });
await page.locator('[data-state="rights"]').first().waitFor({ state: "visible" });
await capture("23-rights-restricted");

await page.goto(`${webBase}/lab/${encodeURIComponent(match.dataset_ids[0])}/${encodeURIComponent(match.session_id)}?view=field&stream=tracking-period-1&t_ns=120000000000`);
await page.getByTestId("pitch-canvas").waitFor({ state: "visible" });
await page.getByRole("region", { name: "Tactical Analysis" }).waitFor({ state: "visible" });
await page.getByRole("tab", { name: "Events", exact: true }).click();
await page.getByText("Unsupported by this source", { exact: false }).waitFor({ state: "visible" });
await capture("24-unsupported-capability");

await page.goto(`${webBase}/performance?dataset=white-cmj-acc-grf&session=cmj-1`);
await page.getByRole("heading", { name: "White CMJ accelerometer + vGRF", exact: true }).waitFor({ state: "visible" });
await page.locator('[data-state="error"]').waitFor({ state: "visible" });
await capture("25-api-error");

await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => undefined);
unavailableCatalogReadModel = true;
await page.goto(`${webBase}/data?domain=sports`);
await page.locator('[data-state="api_unavailable"]').waitFor({ state: "visible" });
await capture("26-api-unavailable");

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
const initialWorldApiRequests = initialWorldRequests.filter((request) => new URL(request.url).pathname.startsWith("/api/"));
const initialWorldDenseRequests = initialWorldRequests.filter((request) =>
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
    firstMatchWorld: initialWorldApiRequests.length,
    denseBeforeWorld: densePaths.length,
    denseFirstMatchWorld: initialWorldDenseRequests.length,
    allCapturedScreens: apiRequests.length,
    denseAcrossCapturedScreens: denseApiRequests.length,
  },
  apiRequests: apiRequests.map((request) => ({ path: request.path, type: request.type })),
  expectedHttpStates: responses.filter((item) => [404, 451, 503].includes(item.status)).map(({ url, status }) => ({ path: new URL(url).pathname, status })),
  consoleErrors,
  usefulWorldRenderMs: worldUsefulRenderMs,
  firstWorldChunkTimings: steps.find((step) => step.name === "07-match-world")?.scriptTimings.filter((item) => /(View-|PitchReplay|PoseScene)/iu.test(item.file)) ?? [],
  echartsLazyLoad: {
    beforeWorld: !steps.find((step) => step.name === "07-match-world")?.scriptTimings.some((item) => /echarts/iu.test(item.file)),
    afterSeasonLab: steps.find((step) => step.name === "16-season-bugarija-match-linkage")?.scriptTimings.find((item) => /echarts/iu.test(item.file)) ?? null,
  },
};
let staticRouteAudit = null;
try {
  const manifest = JSON.parse(await readFile(path.resolve(appDir, "dist/.vite/manifest.json"), "utf8"));
  function staticImports(key, seen = new Set()) {
    if (seen.has(key) || !manifest[key]) return seen;
    seen.add(key);
    for (const dependency of manifest[key].imports ?? []) staticImports(dependency, seen);
    return seen;
  }
  staticRouteAudit = {};
  for (const key of ["src/pages/research.tsx", "src/pages/data.tsx", "src/pages/library.tsx"]) {
    const modules = [...staticImports(key)];
    const files = modules.map((module) => manifest[module]?.file).filter((file) => file?.endsWith(".js"));
    staticRouteAudit[key] = { files, heavy: files.filter((file) => heavyChunk.test(path.basename(file))) };
  }
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}
report.staticRouteAudit = staticRouteAudit;
await writeFile(path.join(viewportDir, "report.json"), JSON.stringify(report, null, 2));
console.log(JSON.stringify({
  viewport: report.viewport,
  corpus: report.liveCorpus,
  returnUrl: report.returnUrl,
  noDenseRequestsBeforeWorld: report.noDenseRequestsBeforeWorld,
  beforeWorldApiRequests: report.apiRequestCounts.beforeWorld,
  firstMatchWorldApiRequests: report.apiRequestCounts.firstMatchWorld,
  denseBeforeWorld: report.apiRequestCounts.denseBeforeWorld,
  denseInFirstMatchWorld: report.apiRequestCounts.denseFirstMatchWorld,
  totalApiRequestsAcrossScreens: report.apiRequestCounts.allCapturedScreens,
  denseRequestsAcrossScreens: report.apiRequestCounts.denseAcrossCapturedScreens,
  staticRouteAudit: report.staticRouteAudit
    ? Object.fromEntries(Object.entries(report.staticRouteAudit).map(([route, value]) => [route, { staticChunks: value.files.length, heavy: value.heavy }]))
    : "Vite did not emit a manifest for this production build.",
  beforeWorldScripts: { count: beforeWorldScripts.length, heavy: preWorldHeavyScripts },
  matchWorldChunks: report.matchWorldChunkFiles.map((file) => {
    const asset = uniqueScripts.find((item) => item.file === file);
    return { file, bytes: asset?.bytes, gzipBytes: asset?.gzipBytes };
  }),
  steps: report.steps.map(({ name, js }) => ({
    name,
    addedAssets: js.length,
    rawBytes: js.reduce((total, asset) => total + asset.bytes, 0),
    gzipBytes: js.reduce((total, asset) => total + asset.gzipBytes, 0),
  })),
  expectedHttpStates: report.expectedHttpStates,
  consoleErrors: report.consoleErrors,
}, null, 2));
await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => undefined);
await page.unrouteAll({ behavior: "wait" });
await context.close();
await browser.close();
