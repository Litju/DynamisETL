import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AnalysisContext, type AnalysisContextValue } from "@/lib/analysis-context";
import { PoseAnalysisPane } from "@/components/pose/PoseAnalysisPane";
import { useAnalysisStore } from "@/lib/state/analysis";

vi.mock("@/components/pose/PoseTelemetry", () => ({
  PoseTelemetry: ({ summaryOnly = false }: { readonly summaryOnly?: boolean }) => (
    <div data-testid={summaryOnly ? "pose-current-sample" : "pose-raw-landmarks"} />
  ),
}));

const STREAM = {
  stream_id: "pose-period-1",
  modality: "pose",
  measurement_class: "MODEL_ESTIMATED",
  subject_id: null,
  trial_id: "period-1",
  device_id: null,
  nominal_sampling_rate_hz: 25,
  si_units: ["m"],
  source_unit: "m",
  coordinate_frame_id: "skillcorner-pose-hybrid-m",
  synchronization_spec_id: "source-clock",
  clock_id: "match-clock",
  skeleton_id: "skillcorner-bodypose-29-landmarks",
  skeleton_joint_names: ["midHip", "lKnee", "rKnee"],
  sample_artifact_ids: ["pose-sample"],
  sample_row_count: 6,
};

const SESSION = {
  dataset_id: "skillcorner-opendata",
  session: {
    session_id: "match-1",
    kind: "match",
    label: "Match",
    started_at: null,
    ended_at: null,
    participant_count: 1,
    trial_count: 1,
    stream_count: 1,
  },
  participants: [{ subject_id: "player-1", role: "player", group_label: "home" }],
  trials: [],
  streams: [STREAM],
};

const SOURCE_ARTIFACT = {
  artifact_id: "pose-sample",
  dataset_id: "skillcorner-opendata",
  stream_id: "pose-period-1",
  layer: "silver",
  relative_path: "silver/pose.parquet",
  format: "parquet",
  compression: "zstd",
  checksum_sha256: "a".repeat(64),
  row_count: 6,
  byte_size: 1000,
  artifact_kind: "sample",
  modality: "pose",
  measurement_class: "MODEL_ESTIMATED",
  si_units: ["m"],
  coordinate_frame_id: "skillcorner-pose-hybrid-m",
  synchronization_spec_id: "source-clock",
  canonical_time_min_ns: 0,
  canonical_time_max_ns: 80_000_000,
  entity_column: "subject_id",
  entity_count: 1,
  entity_ids: ["player-1"],
  entity_observations: [
    { entity_id: "player-1", first_observed_ns: 0, last_observed_ns: 80_000_000, observation_count: 3 },
  ],
};

const LANDMARK_ARTIFACT = {
  ...SOURCE_ARTIFACT,
  artifact_id: "landmark-series",
  layer: "gold",
  relative_path: "gold/pose-landmark.parquet",
  row_count: 3,
  byte_size: 1000,
  artifact_kind: "processing",
  modality: null,
  measurement_class: "PIPELINE_DERIVED",
  algorithm_id: "pose.landmark_kinematics",
  algorithm_version: "1.0.0",
  parameters_hash: "b".repeat(64),
  run_id: "run-landmark",
  artifact_metadata: { series_name: "pose_landmark_kinematics" },
};

const DROPOUT_ARTIFACT = {
  ...LANDMARK_ARTIFACT,
  artifact_id: "pose-quality-dropouts",
  relative_path: "gold/pose-quality-dropouts.parquet",
  row_count: 1,
  algorithm_id: "pose.analysis_quality",
  algorithm_version: "1.1.0",
  run_id: "run-pose-quality",
  artifact_metadata: { series_name: "pose_quality_dropout_intervals" },
};

const METRICS = [
  ["pose.quality.coverage.any_usable_pose", "Usable Pose frame fraction", 0.9, "1", "pose.analysis_quality"],
  ["pose.landmark.coverage.lKnee", "Body-anchor-relative coverage for lKnee", 0.8, "1", "pose.landmark_kinematics"],
  ["pose.landmark.path_length.lKnee", "Body-anchor-relative path length for lKnee", 2.0, "m", "pose.landmark_kinematics"],
  ["pose.landmark.speed_mean.lKnee", "Body-anchor-relative speed mean for lKnee", 1.2, "m/s", "pose.landmark_kinematics"],
  ["pose.bilateral.coverage.knee_included_angle", "Bilateral common-frame coverage for knee", 0.75, "1", "pose.bilateral_geometry"],
].map(([metric_id, metric_name, value_num, si_unit, algorithm_id], index) => ({
  derived_metric_id: `metric-${index}`,
  dataset_id: "skillcorner-opendata",
  metric_id,
  metric_name,
  metric_description: "Precomputed processor result.",
  si_unit,
  measurement_class: "PIPELINE_DERIVED",
  value_kind: "scalar",
  value_num,
  value_json: null,
  subject_id: "player-1",
  session_id: "match-1",
  trial_id: "period-1",
  stream_id: "pose-period-1",
  entity_id: "player-1",
  algorithm_id,
  algorithm_version: "1.0.0",
  parameters_hash: "c".repeat(64),
  code_git_sha: "d".repeat(40),
  run_id: `run-${algorithm_id}`,
  computed_at: null,
  provenance: {},
}));

function json(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function installFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, "http://localhost");
      if (url.pathname === "/api/catalog/datasets/skillcorner-opendata/sessions/match-1") return json(SESSION);
      if (url.pathname === "/api/artifacts/pose-sample") return json(SOURCE_ARTIFACT);
      if (url.pathname === "/api/metrics") return json({ source: "control_plane", total: METRICS.length, limit: 1000, offset: 0, rows: METRICS });
      if (url.pathname === "/api/processing/artifacts") return json([LANDMARK_ARTIFACT, DROPOUT_ARTIFACT]);
      if (url.pathname === "/api/artifacts/landmark-series") return json(LANDMARK_ARTIFACT);
      if (url.pathname === "/api/artifacts/pose-quality-dropouts") return json(DROPOUT_ARTIFACT);
      if (url.pathname.startsWith("/api/metrics/methodology/")) {
        return json({
          metric: { metric_id: "pose.landmark.speed_mean.lKnee", name: "Body-anchor-relative speed mean for lKnee", si_unit: "m/s", measurement_class: "PIPELINE_DERIVED", value_kind: "scalar", description: "Body-relative speed.", algorithm_id: "pose.landmark_kinematics" },
          algorithm: { algorithm_id: "pose.landmark_kinematics", name: "Landmark kinematics", version: "1.0.0", kind: "processor", code_git_sha: "d".repeat(40), parameters_hash: "c".repeat(64), parameters: {}, description: "Gap-safe body-relative kinematics.", citation: null },
          measurement_class_semantics: "Pipeline-derived.",
          measurement_class_never_means: [],
          provenance_fields: ["subject_id", "t_rel_ns"],
        });
      }
      if (url.pathname === "/api/pose/range-report") {
        return json({
          algorithm_id: "pose.range_summary",
          algorithm_version: "1.1.0",
          parameters_hash: "e".repeat(64),
          code_git_sha: "f".repeat(40),
          dataset_id: "skillcorner-opendata",
          session_id: "match-1",
          trial_id: "period-1",
          stream_id: "pose-period-1",
          subject_id: "player-1",
          from_ns: Number(url.searchParams.get("from_ns")),
          to_ns: Number(url.searchParams.get("to_ns")),
          input_artifact_checksums: { pose_source: "a".repeat(64) },
          metrics: [
            {
              metric_id: "pose.range.landmark.speed_mean.lKnee",
              metric_name: "Mean body-anchor-relative speed in selected range for lKnee",
              si_unit: "m/s",
              value_num: 1.1,
              description: "Exact range summary.",
              provenance: { from_ns: 0, to_ns: 80_000_000 },
            },
          ],
          display_note: "Exact processor samples.",
        });
      }
      if (url.pathname === "/api/artifacts/landmark-series/window") {
        return json({
          meta: {
            artifact: LANDMARK_ARTIFACT,
            from_ns: 0,
            to_ns: 80_000_000,
            columns: ["t_rel_ns", "body_relative_speed_lKnee_m_s"],
            source_rows: 3,
            returned_rows: 3,
            canonical_time_min_ns: 0,
            canonical_time_max_ns: 80_000_000,
            reduction: null,
            units: { body_relative_speed_lKnee_m_s: "m/s" },
            coordinate_frame_id: "skillcorner-pose-hybrid-m",
            measurement_class: "PIPELINE_DERIVED",
            display_note: "Exact processor samples.",
          },
          rows: [
            { t_rel_ns: 0, body_relative_speed_lKnee_m_s: 1.0 },
            { t_rel_ns: 40_000_000, body_relative_speed_lKnee_m_s: 1.2 },
            { t_rel_ns: 80_000_000, body_relative_speed_lKnee_m_s: 1.4 },
          ],
        });
      }
      if (url.pathname === "/api/artifacts/pose-quality-dropouts/window") {
        return json({
          meta: {
            artifact: DROPOUT_ARTIFACT,
            from_ns: 0,
            to_ns: 80_000_000,
            columns: ["t_rel_ns", "joint_name", "start_ns", "end_ns_exclusive", "missing_frames", "duration_s"],
            source_rows: 1,
            returned_rows: 1,
            canonical_time_min_ns: 0,
            canonical_time_max_ns: 80_000_000,
            reduction: null,
            units: { duration_s: "s" },
            coordinate_frame_id: "skillcorner-pose-hybrid-m",
            measurement_class: "PIPELINE_DERIVED",
            display_note: "Exact processor intervals.",
          },
          rows: [
            { t_rel_ns: 40_000_000, joint_name: "lKnee", start_ns: 40_000_000, end_ns_exclusive: 80_000_000, missing_frames: 1, duration_s: 0.04 },
          ],
        });
      }
      return json({ detail: `Unhandled ${url.pathname}` });
    }),
  );
}

const context: AnalysisContextValue = {
  datasetId: "skillcorner-opendata",
  sessionId: "match-1",
  trialId: "period-1",
  subjectId: "player-1",
  timeNs: 40_000_000n,
  streamId: "pose-period-1",
  fromNs: null,
  toNs: null,
  metricId: null,
  derivedMetricId: null,
  commitTime: vi.fn(),
  commitRange: vi.fn(),
  selectSubject: vi.fn(),
  selectFieldEntity: vi.fn(),
  selectStream: vi.fn(),
  selectResult: vi.fn(),
};

function renderPane(contextValue: AnalysisContextValue = context) {
  installFetch();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AnalysisContext.Provider value={contextValue}>
        <PoseAnalysisPane />
      </AnalysisContext.Provider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  useAnalysisStore.getState().resetTransient();
});

it("provides keyboard-addressable analysis sections and shared selected-joint controls", async () => {
  renderPane();

  expect(await screen.findByTestId("pose-current-sample")).toBeTruthy();
  expect(screen.getByRole("tablist", { name: "Pose analysis sections" })).toBeTruthy();
  expect(useAnalysisStore.getState().selectedJoint).toBeNull();

  fireEvent.click(screen.getByRole("tab", { name: "Selected joint" }));
  const selector = screen.getByRole("combobox", { name: "Select Pose landmark" });
  fireEvent.change(selector, { target: { value: "lKnee" } });
  expect(useAnalysisStore.getState().selectedJoint).toBe("lKnee");
  fireEvent.click(screen.getByRole("tab", { name: "Quality" }));
  expect(await screen.findByText(/00:00:00.040–00:00:00.080 · 1 frames/)).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Selected joint" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Select Pose landmark" }), { target: { value: "rKnee" } });
  await waitFor(() => expect(useAnalysisStore.getState().selectedJoint).toBe("rKnee"));

  fireEvent.click(screen.getByRole("tab", { name: "Symmetry" }));
  expect(await screen.findByText("Bilateral common-frame coverage for knee")).toBeTruthy();

  fireEvent.click(screen.getByRole("tab", { name: "Raw landmarks" }));
  expect(await screen.findByTestId("pose-raw-landmarks")).toBeTruthy();
});

it("renders the processor waveform from the bounded typed-series window", async () => {
  renderPane();
  fireEvent.click(await screen.findByRole("tab", { name: "Selected joint" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Select Pose landmark" }), { target: { value: "lKnee" } });

  expect(await screen.findByRole("figure", { name: /lKnee Body-relative speed waveform/ })).toBeTruthy();
  await waitFor(() => expect(screen.getByText(/Exact precomputed processor series · 3 points/)).toBeTruthy());
});

it("requests an exact range report from server-side processor series", async () => {
  renderPane({ ...context, fromNs: 0n, toNs: 80_000_000n });
  fireEvent.click(await screen.findByRole("tab", { name: "Selected joint" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Select Pose landmark" }), { target: { value: "lKnee" } });
  fireEvent.click(screen.getByRole("tab", { name: "Range" }));

  expect(await screen.findByText(/pose\.range_summary v1\.1\.0 · subject player-1 · exact processor inputs/)).toBeTruthy();
  expect(screen.getByText("Mean body-anchor-relative speed in selected range for lKnee")).toBeTruthy();
  expect(screen.getByText(/code SHA/)).toBeTruthy();
});
