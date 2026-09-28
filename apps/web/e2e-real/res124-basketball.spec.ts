import { tmpdir } from "node:os";
import path from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

import type {
  BasketballEventPage,
  BasketballFramePage,
  BasketballSpatialGameView,
  GameEditionView,
  GamePage,
  SourceCapabilityView,
  SeasonEditionView,
  SeasonFamilyView,
} from "@/api/types";
import { expectCleanConsole, probe, SC } from "./helpers";

const DATASET_ID = "skillcorner-basketball-opendata";
const PROVIDER_GAME_ID = "114243";

test("RES-124 football → basketball spatial game → SeasonLab", async ({ page, request }) => {
  const console = probe(page);
  const editions = await getJson<GameEditionView[]>(request, "/api/games/editions");
  const acb = editions.find((edition) => edition.dataset_id === DATASET_ID);
  expect(acb, "the metadata-only ACB edition is catalogued").toBeDefined();
  if (!acb) return;
  expect(acb.contest_count).toBe(10);

  const gamePage = await getJson<GamePage>(
    request,
    `/api/games?edition_id=${encodeURIComponent(acb.edition_id)}&limit=1000&offset=0`,
  );
  const contest = gamePage.rows.find((game) => game.provider_game_id === PROVIDER_GAME_ID);
  expect(gamePage.rows).toHaveLength(10);
  const sampleTeamIds = new Set(gamePage.rows.flatMap((game) => game.teams.map((team) => team.team_id)));
  expect(sampleTeamIds.size, "the 10 published sample games represent 17 teams").toBe(17);
  const sourceCapabilities = await getJson<SourceCapabilityView[]>(
    request,
    "/api/catalog/source-capabilities?dataset_id=" + DATASET_ID,
  );
  const contestCapability = sourceCapabilities.find(
    (entry) => entry.external_id === "contest:" + PROVIDER_GAME_ID,
  );
  expect(contestCapability, "source capabilities resolve by the registered dataset id").toBeDefined();
  if (!contestCapability) return;
  expect(contestCapability.local_capabilities).toContain("TRACKING");
  expect(contestCapability.upstream_capabilities).toContain("EVENTS");
  expect(contestCapability.source_file_states).toHaveProperty("dynamic_events");
  expect(contest, "the selected ACB sample game is catalogued").toBeDefined();
  if (!contest) return;
  expect(contest.play_by_play_available).toBe(true);

  const seasonEditions = await getJson<SeasonEditionView[]>(request, "/api/season/editions");
  const seasonEdition = seasonEditions.find((edition) => edition.dataset_id === DATASET_ID);
  expect(seasonEdition, "the ACB season aggregates are registered").toBeDefined();
  if (!seasonEdition) return;
  const seasonShots = await getJson<SeasonFamilyView>(
    request,
    `/api/season/editions/${encodeURIComponent(seasonEdition.edition_id)}/families/shots`,
  );
  expect(seasonShots.teams).toHaveLength(18);

  const spatial = await getJson<BasketballSpatialGameView>(
    request,
    `/api/basketball/contests/${contest.contest_id}`,
  );
  expect(spatial.tracking_materialized).toBe(true);
  expect(spatial.events_materialized).toBe(true);
  expect(spatial.frame_rate_hz).toBe(25);
  expect(spatial.units).toBe("ft");
  expect(spatial.spatial_reference_id).toBe("skillcorner-basketball-court-ft");
  expect(spatial.players.length).toBeGreaterThanOrEqual(10);
  expect(spatial.periods).toHaveLength(4);
  expect(spatial.periods[0]!.dead_time_frames).toBeGreaterThan(0);

  const firstPeriod = spatial.periods[0]!;
  const activeFrame = await getJson<BasketballFramePage>(
    request,
    `/api/basketball/contests/${contest.contest_id}/frames?period=1&from_frame=${firstPeriod.first_active_frame}&limit=1`,
  );
  expect(activeFrame.rows[0]!.players).toHaveLength(10);
  expect(activeFrame.rows[0]!.ball).not.toBeNull();
  expect(activeFrame.rows[0]!.shot_clock_s).not.toBeNull();

  const deadFrame = await getJson<BasketballFramePage>(
    request,
    `/api/basketball/contests/${contest.contest_id}/frames?period=1&from_frame=${firstPeriod.first_frame}&limit=1`,
  );
  expect(deadFrame.rows[0]!.is_dead_time).toBe(true);
  expect(deadFrame.rows[0]!.players).toEqual([]);
  expect(deadFrame.rows[0]!.ball).toBeNull();
  expect(deadFrame.rows[0]!.game_clock_s).not.toBeNull();

  const periodEvents = await getAllEvents(request, contest.contest_id, 1);
  const seekTargets = ["shots", "timeouts", "picks", "drives"].map((family) => {
    const index = periodEvents.findIndex(
      (event) =>
        event.provider_event_type === family
        && typeof event.source_clock?.linked_frame_idx === "number",
    );
    return { family, index, event: periodEvents[index] };
  });
  for (const target of seekTargets) {
    expect(target.index, `${target.family} has an exact source-frame link`).toBeGreaterThanOrEqual(0);
  }

  // Start in real football MatchLab, then open the ACB sample through GameLab.
  await page.goto(`${SC}?view=matchlab&stream=tracking-period-1`);
  await expect(page.getByTestId("matchlab-canvas-root")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Analysis context" })).toContainText("Brisbane Roar");
  await page.getByRole("button", { name: "Match World — switch World" }).click();
  await page.getByRole("menuitem", { name: /Game World/ }).click();
  await expect(page.getByTestId("gamelab")).toBeVisible();
  await expect(page.getByTestId("gamelab").getByText("Game World", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Competition edition" }).selectOption(acb.edition_id);
  const acbGames = page.getByRole("table", { name: "ACB contests" });
  await expect(acbGames).toBeVisible();
  const contestRow = acbGames.getByRole("row").filter({ hasText: PROVIDER_GAME_ID });
  await expect(contestRow).toBeVisible();
  await contestRow.click();
  await expect(page.getByTestId("gamelab")).toHaveAttribute("data-sport", "basketball");
  await page.getByRole("button", { name: "Open spatial court" }).first().click();
  await expect(page.getByTestId("basketball-court")).toBeVisible();
  await expect(page.getByLabel("Basketball period")).toHaveValue("1");
  await expect(page.getByText("Game clock")).toBeVisible();
  await expect(page.getByText("Shot clock")).toBeVisible();

  const timeline = page.getByRole("slider", { name: "Frame timeline" });
  await expect(timeline).toHaveValue(String(firstPeriod.first_active_frame));
  const selectedPlayer = spatial.players.find(
    (player) => player.subject_id === activeFrame.rows[0]!.players[0]!.subject_id,
  );
  expect(selectedPlayer, "an active source tracking player resolves through the roster").toBeDefined();
  if (!selectedPlayer) return;
  await page.getByLabel("Selected player").selectOption(selectedPlayer.subject_id);
  expect(new URL(page.url()).searchParams.get("player")).toBe(selectedPlayer.subject_id);
  await expect(
    page.getByRole("button", { name: `Select ${selectedPlayer.display_name}, jersey ${selectedPlayer.jersey ?? "unknown"}` }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Select ball" }).click();
  await expect(page.getByRole("button", { name: "Deselect ball" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // Scrubbing to dead time preserves clocks and leaves the court empty.
  await timeline.press("Home");
  await expect(page.getByTestId("dead-time-frame")).toBeVisible();
  await expect(page.getByTestId("basketball-ball")).toHaveCount(0);
  await expect(timeline).toHaveValue(String(firstPeriod.first_frame));

  // Every available action family seeks to its exact source frame and time.
  let eventOffset = 0;
  for (const target of [...seekTargets].sort((left, right) => left.index - right.index)) {
    while (eventOffset < Math.floor(target.index / 500) * 500) {
      await page.getByRole("button", { name: "Next event page" }).click();
      eventOffset += 500;
    }
    const event = target.event!;
    const linkedFrameIdx = event.source_clock?.linked_frame_idx;
    expect(typeof linkedFrameIdx).toBe("number");
    if (typeof linkedFrameIdx !== "number" || event.canonical_time_ns === null) return;
    const eventButton = page.locator(`[data-event-id="${event.source_event_id}"]`);
    await expect(eventButton).toBeVisible();
    await eventButton.click();
    await expect(timeline).toHaveValue(String(linkedFrameIdx));
    await expect(page.getByTestId("basketball-court")).toHaveAttribute(
      "data-frame-idx",
      String(linkedFrameIdx),
    );
    await expect(page.getByTestId("basketball-court")).toHaveAttribute(
      "data-frame-time-ns",
      String(event.canonical_time_ns),
    );
    await expect(eventButton).toHaveAttribute("aria-pressed", "true");
    const eventFrame = await getJson<BasketballFramePage>(
      request,
      `/api/basketball/contests/${contest.contest_id}/frames?period=1&from_frame=${linkedFrameIdx}&limit=1`,
    );
    expect(eventFrame.rows[0]!.frame_idx).toBe(linkedFrameIdx);
    expect(eventFrame.rows[0]!.canonical_time_ns).toBe(event.canonical_time_ns);
    if (target.family === "shots") {
      await page.screenshot({
        path: path.join(tmpdir(), "dynamis-res124-basketball-spatial.png"),
        fullPage: false,
      });
    }
  }

  await page.getByRole("button", { name: /SeasonLab · Shots \/ Drives \/ Picks/ }).click();
  await expect(page).toHaveURL(/\/season\?/);
  await expect(page.locator(".season-lab")).toHaveAttribute("data-family", "shots");
  const seasonEvidence = page.getByRole("complementary", { name: "Metric evidence" });
  await expect(seasonEvidence).toContainText("Offense-only season aggregates");
  await expect(seasonEvidence).toContainText("293 of 327 ACB 2025-2026 games");
  await expect(seasonEvidence).toContainText("18-team season population");
  await expect(seasonEvidence).toContainText("10 published sample games represent 17 teams");
  await page.screenshot({
    path: path.join(tmpdir(), "dynamis-res124-seasonlab-coverage.png"),
    fullPage: false,
  });
  await expect(page.getByRole("tab", { name: /Shots/ })).toBeVisible();
  await page.getByRole("tab", { name: /Drives/ }).click();
  await expect(page.locator(".season-lab")).toHaveAttribute("data-family", "drives");
  await page.getByRole("tab", { name: /Picks/ }).click();
  await expect(page.locator(".season-lab")).toHaveAttribute("data-family", "picks");

  // Football gets its own URL context; no ACB playhead or selection survives.
  await page.goto(`${SC}?view=matchlab&stream=tracking-period-1`);
  await expect(page.getByTestId("matchlab-canvas-root")).toBeVisible();
  await expect(page.getByTestId("basketball-spatial-game")).toHaveCount(0);
  const footballParams = new URL(page.url()).searchParams;
  expect(footballParams.get("contest")).toBeNull();
  expect(footballParams.get("frame")).toBeNull();
  expect(footballParams.get("event")).toBeNull();
  await expectCleanConsole(console);
});

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `${path} returns real serving data`).toBeTruthy();
  return (await response.json()) as T;
}

async function getAllEvents(
  request: APIRequestContext,
  contestId: string,
  period: number,
): Promise<BasketballEventPage["rows"]> {
  const rows: BasketballEventPage["rows"] = [];
  for (let offset = 0; ; offset += 500) {
    const page = await getJson<BasketballEventPage>(
      request,
      `/api/basketball/contests/${contestId}/events?period=${period}&limit=500&offset=${offset}`,
    );
    rows.push(...page.rows);
    if (rows.length >= page.total) return rows;
    expect(page.rows.length, "event pagination makes forward progress").toBeGreaterThan(0);
  }
}
