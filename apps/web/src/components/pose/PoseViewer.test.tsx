import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AnalysisContext, type AnalysisContextValue } from "@/lib/analysis-context";
import { PoseViewer } from "@/components/pose/PoseViewer";
import { useAnalysisStore } from "@/lib/state/analysis";

vi.mock("@/components/pose/PoseScene", () => ({
  default: () => <div data-testid="pose-scene-stub" />,
}));

const POSE_STREAM = {
  stream_id: "pose-1",
  modality: "pose",
  measurement_class: "MODEL_ESTIMATED",
  subject_id: "s1",
  trial_id: null,
  device_id: null,
  nominal_sampling_rate_hz: 25,
  si_units: ["m"],
  source_unit: "m",
  coordinate_frame_id: "skillcorner-pose-hybrid-m",
  synchronization_spec_id: "skillcorner-source-provided-match-clock",
  clock_id: "skillcorner-match-clock",
  skeleton_id: "skillcorner-bodypose-29-landmarks",
  sample_artifact_ids: ["pose-sample"],
  sample_row_count: 3,
};

const SESSION = {
  dataset_id: "demo",
  session: {
    session_id: "s1",
    kind: "match",
    label: null,
    started_at: null,
    ended_at: null,
    participant_count: 1,
    trial_count: 0,
    stream_count: 1,
  },
  participants: [],
  trials: [],
  streams: [POSE_STREAM],
};

const ARTIFACT = {
  artifact_id: "pose-sample",
  dataset_id: "demo",
  stream_id: "pose-1",
  layer: "silver",
  relative_path: "silver/demo/pose/sample.parquet",
  format: "parquet",
  compression: "zstd",
  checksum_sha256: "a".repeat(64),
  row_count: 3,
  byte_size: 2048,
  artifact_kind: "sample",
  modality: "pose",
  measurement_class: "MODEL_ESTIMATED",
  si_units: ["m"],
  coordinate_frame_id: "skillcorner-pose-hybrid-m",
  synchronization_spec_id: "skillcorner-provided",
  // The viewer sizes its window from the artifact's own canonical bounds and
  // scopes it to one subject, so the fixture must serve both.
  canonical_time_min_ns: 0,
  canonical_time_max_ns: 100_000_000,
  entity_column: "subject_id",
  entity_count: 1,
  entity_ids: ["s1", "s2"],
  entity_observations: [
    { entity_id: "s1", first_observed_ns: 0, last_observed_ns: 100_000_000, observation_count: 3 },
    { entity_id: "s2", first_observed_ns: 20_000_000, last_observed_ns: 100_000_000, observation_count: 2 },
  ],
};

const POSE_ROWS = [
  { t_rel_ns: 0, subject_id: "s1", joint_name: "nose", is_available: true, x_m: 0, y_m: 0, z_m: 0.1, error_m: 0.02 },
  { t_rel_ns: 0, subject_id: "s1", joint_name: "lHip", is_available: true, x_m: 0, y_m: 0, z_m: -0.4, error_m: 0.03 },
  { t_rel_ns: 0, subject_id: "s1", joint_name: "lKnee", is_available: false, x_m: null, y_m: null, z_m: null, error_m: null },
];

function windowBody(reduction: unknown = null) {
  return {
    meta: {
      artifact: ARTIFACT,
      from_ns: 0,
      to_ns: 40_000_000,
      columns: [
        "t_rel_ns",
        "subject_id",
        "joint_name",
        "is_available",
        "x_m",
        "y_m",
        "z_m",
        "error_m",
      ],
      source_rows: 3,
      returned_rows: 3,
      canonical_time_min_ns: 0,
      canonical_time_max_ns: 40_000_000,
      reduction,
      units: { x_m: "m", y_m: "m", z_m: "m", error_m: "m" },
      coordinate_frame_id: "skillcorner-pose-hybrid-m",
      measurement_class: "MODEL_ESTIMATED",
      display_note: "Exact.",
    },
    rows: POSE_ROWS,
  };
}

function installFetch(options: { reduced?: boolean; withOverlays?: boolean } = {}): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, "http://localhost");
      if (url.pathname === "/api/catalog/datasets/demo/sessions/s1") return json(SESSION);
      if (url.pathname === "/api/artifacts/pose-sample") return json(ARTIFACT);
      if (url.pathname === "/api/artifacts/pose-sample/window") {
        return json(
          windowBody(
            options.reduced
              ? {
                  method: "min_max_envelope_per_time_bucket",
                  parameters: {},
                  source_points: 3,
                  returned_points: 2,
                  note: "display only",
                }
              : null,
          ),
        );
      }
      if (url.pathname === "/api/metrics") {
        return json({
          source: "control_plane",
          total: 1,
          limit: 50,
          offset: 0,
          rows: [
            {
              derived_metric_id: "dm-1",
              dataset_id: "demo",
              metric_id: "pose.angular_rom.left_knee",
              metric_name: "knee ROM",
              metric_description: null,
              si_unit: "rad",
              measurement_class: "PIPELINE_DERIVED",
              value_kind: "scalar",
              value_num: 2.1,
              value_json: null,
              subject_id: "s1",
              session_id: "s1",
              trial_id: null,
              stream_id: "pose-1",
              entity_id: "s1",
              algorithm_id: "pose.translation_invariant_kinematics",
              algorithm_version: "1.0.0",
              parameters_hash: null,
              code_git_sha: "b".repeat(40),
              run_id: "run-1",
              computed_at: null,
              provenance: {},
            },
          ],
        });
      }
      if (url.pathname.startsWith("/api/metrics/methodology/")) {
        return json({
          metric: {
            metric_id: "pose.angular_rom.left_knee",
            name: "knee ROM",
            si_unit: "rad",
            measurement_class: "PIPELINE_DERIVED",
            value_kind: "scalar",
            description: null,
            algorithm_id: "pose.translation_invariant_kinematics",
          },
          algorithm: {
            algorithm_id: "pose.translation_invariant_kinematics",
            name: "Pose kinematics",
            version: "1.0.0",
            kind: "processor",
            code_git_sha: "b".repeat(40),
            parameters_hash: "c".repeat(64),
            parameters: options.withOverlays
              ? {
                  segments: [{ name: "left_thigh", start_landmark: "lHip", end_landmark: "lKnee" }],
                  angles: [
                    {
                      name: "left_knee",
                      vertex_landmark: "lKnee",
                      first_landmark: "lHip",
                      second_landmark: "nose",
                    },
                  ],
                }
              : {},
            description: null,
            citation: null,
          },
          measurement_class_semantics: "processor",
          measurement_class_never_means: [],
          provenance_fields: [],
        });
      }
      return json({ detail: `unhandled ${url.pathname}` }, 404);
    }),
  );
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderViewer(overrides: Partial<AnalysisContextValue> = {}) {
  const context: AnalysisContextValue = {
    datasetId: "demo",
    sessionId: "s1",
    trialId: null,
    subjectId: null,
    timeNs: null,
    streamId: "pose-1",
    fromNs: null,
    toNs: null,
    metricId: null,
    derivedMetricId: null,
    commitTime: vi.fn(),
    commitRange: vi.fn(),
    selectSubject: vi.fn(),
    selectStream: vi.fn(),
    selectResult: vi.fn(),
    ...overrides,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AnalysisContext.Provider value={context}>
        <PoseViewer />
      </AnalysisContext.Provider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  useAnalysisStore.setState({
    playheadNs: null,
    committedTimeNs: null,
    selectedJoint: null,
    subjectSwitching: false,
  });
});

it("labels the local analytical frame and exposes provider error radius context", async () => {
  installFetch({ withOverlays: true });
  renderViewer();
  expect(
    await screen.findByText(/local analytical frame · Z is player-centroid-relative/),
  ).toBeInTheDocument();
  expect(screen.getByText(/2 observed · 1 unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/mean provider p90 predicted error radius 0.0250 m/)).toBeInTheDocument();
  expect(await screen.findByTestId("pose-scene-stub")).toBeInTheDocument();
  expect(
    await screen.findByText(/1 segment\(s\), 1 angle\(s\) from processor parameters/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("checkbox", { name: "provider p90 predicted error radius" }),
  ).toBeInTheDocument();
});

it("states when no processor overlays are declared", async () => {
  installFetch();
  renderViewer();
  expect(
    await screen.findByText("none declared for this stream's processor revision"),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("pose-scene-stub")).toBeInTheDocument();
});

it("refuses a reduced pose window", async () => {
  installFetch({ reduced: true });
  renderViewer();
  expect(await screen.findByText("This window is display-reduced.")).toBeInTheDocument();
  expect(screen.queryByTestId("pose-scene-stub")).not.toBeInTheDocument();
});

it("requires a pose stream and never renders another modality", async () => {
  installFetch();
  renderViewer({ streamId: null });
  expect(await screen.findByText("No stream selected.")).toBeInTheDocument();
});

it("distinguishes a subject with observations from an empty current window", async () => {
  installFetch();
  renderViewer({ subjectId: "s2" });
  expect(
    await screen.findByText("Subject s2 is not observed at the current time."),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("pose-scene-stub")).not.toBeInTheDocument();
});

it("switches the subject with one exact target-time navigation transaction", async () => {
  installFetch();
  const selectSubject = vi.fn();
  renderViewer({ subjectId: "s1", selectSubject });
  const picker = await screen.findByLabelText("subject");
  useAnalysisStore.getState().commitTime(50_000_000n);
  fireEvent.change(picker, { target: { value: "s2" } });
  expect(useAnalysisStore.getState().committedTimeNs).toBe(20_000_000n);
  expect(useAnalysisStore.getState().playing).toBe(false);
  expect(selectSubject).toHaveBeenCalledWith("s2", { targetTimeNs: 20_000_000n });
});
