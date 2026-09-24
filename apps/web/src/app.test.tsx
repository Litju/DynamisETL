import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppRouter } from "@/router";
import type { DatasetDetail, DatasetSummary, MetricPage, SessionDetail } from "@/api/types";

// jsdom has no canvas rasteriser, so the real chart engine cannot initialise
// here. The shell test is about routing, durable state and composition; the
// option builders have their own tests against the real contracts.
vi.mock("echarts", () => ({
  init: () => ({
    setOption: () => undefined,
    resize: () => undefined,
    dispose: () => undefined,
    getOption: () => ({}),
    on: () => undefined,
  }),
}));

const DATASET: DatasetSummary = {
  dataset_id: "skillcorner-opendata",
  name: "SkillCorner Open Data",
  provider: "SkillCorner",
  domain: "football",
  doi: null,
  upstream_urls: ["https://github.com/SkillCorner/opendata"],
  modalities: ["tracking", "pose", "event"],
  ingested_modalities: ["pose", "tracking"],
  license: {
    policy_id: "skillcorner-opendata",
    identifier: "CC BY 4.0",
    status: "declared",
    attribution_required: true,
    noncommercial_only: false,
    share_alike: false,
    redistribution: "conditional",
    local_only: false,
    restrictions: [],
    notice: "CC BY 4.0; attribution required; redistribution: conditional",
  },
  version_count: 1,
  session_count: 1,
  subject_count: 23,
  trial_count: 2,
  stream_count: 3,
  metric_count: 4,
  quality_issue_count: 1,
};

const DATASET_DETAIL: DatasetDetail = {
  ...DATASET,
  adapter_id: "skillcorner-open-data",
  initial_scope: "match and player tracking",
  v1_role: "accepted tracking source",
  versions: [
    {
      citation: null,
      release_date: null,
      retrieval_status: "fetched",
      retrieved_at: null,
      upstream_url: "https://github.com/SkillCorner/opendata",
      version: "v1",
    },
  ],
};

const SESSION: SessionDetail = {
  dataset_id: "skillcorner-opendata",
  session: {
    session_id: "1925299",
    kind: "match",
    label: "Eintracht Frankfurt vs Bayern",
    started_at: null,
    ended_at: null,
    participant_count: 23,
    trial_count: 2,
    stream_count: 3,
  },
  participants: [{ subject_id: "809166", role: "player", group_label: "home" }],
  trials: [
    {
      trial_id: "period-1",
      subject_id: null,
      parent_trial_id: null,
      label: "first half",
      started_at: null,
      ended_at: null,
    },
  ],
  streams: [
    {
      stream_id: "pose-period-1",
      modality: "pose",
      measurement_class: "MODEL_ESTIMATED",
      subject_id: "809166",
      trial_id: "period-1",
      device_id: null,
      nominal_sampling_rate_hz: 25.0,
      si_units: ["m"],
      source_unit: "m",
      coordinate_frame_id: "skillcorner-pose-hybrid-m",
      synchronization_spec_id: "skillcorner-source-provided-match-clock",
      clock_id: "skillcorner-match-clock",
      skeleton_id: "skillcorner-bodypose-29-landmarks",
      sample_artifact_ids: [],
      sample_row_count: 0,
    },
  ],
};

const METRICS: MetricPage = {
  source: "control_plane",
  total: 1,
  limit: 250,
  offset: 0,
  rows: [
    {
      derived_metric_id: "dm-pose-rom",
      dataset_id: "skillcorner-opendata",
      metric_id: "pose.angular_rom.left_knee",
      metric_name: "Range of motion for angle left_knee",
      metric_description: "max - min of the observed angle.",
      si_unit: "rad",
      measurement_class: "PIPELINE_DERIVED",
      value_kind: "scalar",
      value_num: 2.7,
      value_json: null,
      subject_id: "809166",
      session_id: "1925299",
      trial_id: "period-1",
      stream_id: "pose-period-1",
      entity_id: "809166",
      algorithm_id: "pose.translation_invariant_kinematics",
      algorithm_version: "1.0.0",
      parameters_hash: "e".repeat(64),
      code_git_sha: "b".repeat(40),
      run_id: "run-pose",
      computed_at: "2026-09-18T12:00:00+00:00",
      provenance: {},
    },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetchStub(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const raw =
        typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(raw, "http://localhost").pathname;
      if (path === "/api/serving/status") {
        return jsonResponse({
          database: "ok",
          db_schema: "dynamis",
          gold_schema: "gold",
          gold_published: false,
          dataset_count: 1,
          metric_count: 1,
          run_count: 1,
          quality_issue_count: 0,
        });
      }
      if (path === "/api/catalog/datasets") {
        return jsonResponse([DATASET]);
      }
      if (path === "/api/catalog/datasets/skillcorner-opendata") {
        return jsonResponse(DATASET_DETAIL);
      }
      if (path === "/api/catalog/datasets/skillcorner-opendata/sessions") {
        return jsonResponse([SESSION.session]);
      }
      if (path === "/api/catalog/datasets/skillcorner-opendata/sessions/1925299") {
        return jsonResponse(SESSION);
      }
      if (path === "/api/metrics") {
        return jsonResponse(METRICS);
      }
      if (path === "/api/metrics/definitions") {
        return jsonResponse([
          {
            metric_id: "pose.angular_rom.left_knee",
            name: "Range of motion for angle left_knee",
            si_unit: "rad",
            measurement_class: "PIPELINE_DERIVED",
            value_kind: "scalar",
            description: null,
            algorithm_id: "pose.translation_invariant_kinematics",
            dataset_ids: ["skillcorner-opendata"],
            value_count: 4,
          },
        ]);
      }
      return jsonResponse({ detail: `unhandled ${path}` }, 404);
    }),
  );
}

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("workbench shell", () => {
  beforeEach(() => {
    installFetchStub();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the fixed instrument shell on the catalog route", async () => {
    renderAt("/catalog");
    expect(await screen.findByRole("navigation", { name: "Product surfaces" })).toBeInTheDocument();
    expect(screen.getByText(/Performance Laboratory/)).toBeInTheDocument();
    expect(await screen.findByText("SkillCorner Open Data")).toBeInTheDocument();
    expect(screen.getByText("CC BY 4.0")).toBeInTheDocument();
  });

  it("does not advertise an un-ingested event laboratory", async () => {
    renderAt("/catalog?dataset=skillcorner-opendata");

    expect(await screen.findByRole("link", { name: "Field" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Pose" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Events" })).not.toBeInTheDocument();
    expect(screen.queryByTitle("Events laboratory available for this dataset")).not.toBeInTheDocument();
  });

  it("compacts the inspector to a rail where nothing is inspectable", async () => {
    const user = userEvent.setup();
    renderAt("/catalog");
    // The catalog owns its own dataset evidence, so the inspector must not
    // reserve flagship width with an empty pane.
    await screen.findByRole("navigation", { name: "Product surfaces" });
    expect(screen.queryByRole("region", { name: "Inspector" })).not.toBeInTheDocument();

    // It stays one click away.
    await user.click(screen.getByRole("button", { name: "Open the inspector" }));
    expect(await screen.findByRole("region", { name: "Inspector" })).toBeInTheDocument();
  });

  it("restores the full durable context from a deep link", async () => {
    renderAt(
      "/lab/skillcorner-opendata/1925299?trial=period-1&subject=809166&view=overview&t_ns=2987480000000",
    );
    // Context bar: dataset, session, trial, subject.
    expect(await screen.findByText("skillcorner-opendata")).toBeInTheDocument();
    expect(screen.getAllByText("1925299").length).toBeGreaterThan(0);
    expect(screen.getByText("period-1")).toBeInTheDocument();
    expect(screen.getAllByText("809166").length).toBeGreaterThan(0);
    // Committed playhead is restored from decimal nanosecond text.
    expect(screen.getAllByText("00:49:47.480").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2987480000000 ns").length).toBeGreaterThan(0);
    // Derived metric with its measurement class is listed in the overview.
    expect(await screen.findByText("pose.angular_rom.left_knee")).toBeInTheDocument();
    expect(screen.getAllByText("pipeline-derived").length).toBeGreaterThan(0);
    // Stream contracts are subordinate to the analysis but stay one click
    // away, and the synchronization specification remains explicit.
    const contracts = screen.getByRole("button", { name: /Stream contracts/ });
    expect(contracts).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(contracts);
    expect(
      await screen.findByText(/skillcorner-source-provided-match-clock/),
    ).toBeInTheDocument();
  });

  it("opens a non-overview view from the deep link without inventing results", async () => {
    renderAt("/lab/skillcorner-opendata/1925299?stream=pose-period-1&view=pose");
    await screen.findByRole("tab", { name: "pose" });
    // The stub session declares no canonical pose artifact, so the pose viewer
    // must say so explicitly instead of rendering an empty scene.
    expect(
      await screen.findByText("No canonical pose artifact is registered."),
    ).toBeInTheDocument();
    expect(screen.queryByText("pose.angular_rom.left_knee")).not.toBeInTheDocument();
  });

  it("keeps compare mode on an explicit empty state until configured", async () => {
    renderAt("/compare");
    // Discovery comes first: the metric vocabulary is offered rather than an
    // internal id being demanded.
    expect(await screen.findByText("Choose a metric to compare.")).toBeInTheDocument();
    expect(screen.getByLabelText("Metric")).toBeInTheDocument();
  });
});



