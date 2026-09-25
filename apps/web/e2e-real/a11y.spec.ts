import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { DFL, SC } from "./helpers";

/** RES-112 real-data accessibility: axe on every flagship state, no mocks. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function expectNoSeriousViolations(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const serious = results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => ({ id: violation.id, help: violation.help, targets: violation.nodes.map((node) => node.target) }));
  expect(serious, `${label}\n${JSON.stringify(serious, null, 2)}`).toEqual([]);
}

const ROUTES: ReadonlyArray<readonly [string, string]> = [
  ["catalog", "/catalog"],
  ["DFL overview", `${DFL}?view=overview`],
  ["SkillCorner pose", `${SC}?view=pose&stream=pose-period-1`],
  ["compare", "/compare"],
  ["methods", "/methods"],
  ["quality", "/quality"],
  ["runs", "/runs"],
];

async function expectRouteReady(page: Page, label: string) {
  switch (label) {
    case "catalog":
      await expect(page.getByText("DFL/Sportec IDSSE")).toBeVisible();
      break;
    case "DFL overview":
      await expect(page.getByText(/Highest total locomotor distance/i)).toBeVisible();
      break;
    case "SkillCorner pose":
      await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
      await expect(page.getByTestId("pose-telemetry")).toContainText(/\d+ observed · \d+ unavailable/);
      break;
    case "compare":
      await expect(page.getByRole("heading", { name: "Compare served values" })).toBeVisible();
      await expect(page.getByLabel("Metric")).toBeEnabled();
      break;
    case "methods":
      await expect(page.getByRole("heading", { name: "Methodology and provenance" })).toBeVisible();
      await expect(page.getByLabel("Metric")).toBeEnabled();
      break;
    case "quality":
      await expect(page.getByRole("heading", { name: "Quality & rights" })).toBeVisible();
      await expect(page.getByLabel("Filter quality issues by dataset")).toBeVisible();
      break;
    case "runs":
      await expect(page.getByText(/^[\d,]+ of [\d,]+ runs$/)).toBeVisible();
      break;
  }
}

async function expectTacticalTabReady(page: Page, tab: string) {
  const panel = page.getByTestId("tactical-tabpanel");
  await expect(panel).toHaveAttribute("data-view", tab.toLowerCase());
  await expect(panel.getByText("Loading tactical capability")).toHaveCount(0);
  await expect(panel.getByText("Loading tactical series")).toHaveCount(0);
  const readyText: Record<string, RegExp> = {
    Live: /POSSESSION AND BALL CONTEXT|No source possession context/i,
    Structure: /DEF \/ MID \/ ATT|No functional-unit geometry/,
    Relations: /Choose a relation|Local relations/,
    Space: /Occupied area|Territory · clipped Voronoi/,
    Range: /No range is committed/,
    Events: /source events/i,
    Report: /Deterministic report/,
  };
  await expect(panel.getByText(readyText[tab] ?? /.*/).first()).toBeVisible();
}

for (const [label, route] of ROUTES) {
  test(`axe (real data): ${label}`, async ({ page }) => {
    await page.goto(route);
    await expectRouteReady(page, label);
    await expectNoSeriousViolations(page, label);
  });
}

test("axe (real data): every DFL tactical tab", async ({ page }) => {
  await page.goto(`${DFL}?view=field&stream=tracking-period-1&t_ns=300020000000`);
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  const pane = page.getByRole("region", { name: "Tactical Analysis" });
  for (const tab of ["Live", "Structure", "Relations", "Space", "Range", "Events", "Report"]) {
    await pane.getByRole("tab", { name: tab, exact: true }).click();
    await expectTacticalTabReady(page, tab);
    await expectNoSeriousViolations(page, `DFL field · ${tab}`);
  }
});

test("tactical analysis can collapse to and reopen from its rail", async ({ page }) => {
  await page.goto(`${DFL}?view=field&stream=tracking-period-1`);
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  const pane = page.getByRole("region", { name: "Tactical Analysis" });
  await expect(pane).toBeVisible();
  await pane.getByRole("button", { name: "Collapse tactical analysis" }).click();
  await expect(pane).toHaveCount(0);
  const railButton = page.getByRole("button", { name: "Open the tactical analysis" });
  await expect(railButton).toBeVisible();
  await railButton.click();
  await expect(pane).toBeVisible();
});

test("axe (real data): Pose all-subject scope and SkillCorner unsupported events", async ({ page }) => {
  await page.goto(`${SC}?view=pose&stream=pose-period-1`);
  await expect(page.getByTestId("pose-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await page.getByTestId("pose-all-subjects-toggle").click();
  await expect(page.getByText(/all subjects · fixed camera \(\d+\)/)).toBeVisible();
  await expectNoSeriousViolations(page, "pose all subjects");
  await page.goto(`${SC}?view=field&stream=tracking-period-1&tactical=events`);
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await expectNoSeriousViolations(page, "SkillCorner events unsupported");
});

test("keyboard: tactical tabs, layer toggles and timeline are reachable with visible focus", async ({ page }) => {
  await page.goto(`${SC}?view=field&stream=tracking-period-1`);
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  const live = page.getByRole("tab", { name: "Live", exact: true });
  await live.focus();
  const outline = await live.evaluate((element) => getComputedStyle(element).outlineStyle);
  expect(outline).not.toBe("none");
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Report", exact: true })).toBeFocused();
  const occupiedArea = page.getByRole("button", { name: /Occupied area/ });
  const before = await occupiedArea.getAttribute("aria-pressed");
  await occupiedArea.focus();
  await page.keyboard.press("Enter");
  await expect(occupiedArea).toHaveAttribute("aria-pressed", before === "true" ? "false" : "true");
  const timeline = page.getByTestId("transport-timeline");
  await timeline.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/t_ns=100000000(&|$)/);
});

test("reduced motion: tab indicator does not animate", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(`${SC}?view=field&stream=tracking-period-1`);
  await expect(page.getByTestId("pitch-canvas")).toHaveAttribute("data-renderer-ready", "true");
  await page.getByRole("tab", { name: "Space", exact: true }).click();
  const duration = await page
    .locator("#tactical-tab-space .t-tab-indicator")
    .evaluate((element) => getComputedStyle(element).animationDuration);
  expect(Number.parseFloat(duration)).toBeLessThan(0.01);
});
