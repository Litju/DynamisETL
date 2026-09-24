import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AnalysisContext, type AnalysisContextValue } from "@/lib/analysis-context";
import { MatchFrameContextProvider } from "@/lib/match-frame-context";
import type { TrackingWindowBuffers } from "@/components/matchlab/frame-buffers";
import { PitchReplay, sessionTeams, shirtLabels } from "@/components/pitch/PitchReplay";
import { useAnalysisStore } from "@/lib/state/analysis";

const setFrame = vi.fn();
const setTrail = vi.fn();
const setEvents = vi.fn();
const setLayers = vi.fn();
const setTacticalOverlay = vi.fn();
const resetView = vi.fn();
const destroy = vi.fn();
const createPitchRenderer = vi.fn(async (..._args: unknown[]) => ({
  setFrame,
  setTrail,
  setEvents,
  setLayers,
  setTacticalOverlay,
  resetView,
  destroy,
}));

// The mock replaces the whole module, so the layer defaults the component
// reads as a value have to come with it.
vi.mock("@/components/pitch/pitch-renderer", () => ({
  createPitchRenderer: (...args: unknown[]) => createPitchRenderer(...args),
  DEFAULT_PITCH_LAYERS: { trails: true, labels: true, events: true, geometry: true, territory: false, influence: false },
  shortEntityLabel: (objectId: string) => objectId,
}));

const STREAM = {
  stream_id: "tracking-1",
  modality: "tracking",
  measurement_class: "MODEL_ESTIMATED",
  subject_id: null,
  trial_id: null,
  device_id: null,
  nominal_sampling_rate_hz: 10,
  si_units: ["m"],
  source_unit: "m",
  coordinate_frame_id: "skillcorner-pitch-m",
  synchronization_spec_id: "skillcorner-source-provided-match-clock",
  clock_id: "skillcorner-match-clock",
  skeleton_id: null,
  sample_artifact_ids: ["tracking-sample"],
  sample_row_count: 4,
};

const SESSION = {
  dataset_id: "demo",
  session: {
    session_id: "s1",
    kind: "match",
    label: null,
    started_at: null,
    ended_at: null,
    participant_count: 3,
    trial_count: 1,
    stream_count: 1,
  },
  participants: [
    { subject_id: "p1", role: "player", group_label: "home" },
    { subject_id: "p2", role: "player", group_label: "away" },
  ],
  trials: [],
  streams: [STREAM],
};

const ARTIFACT = {
  artifact_id: "tracking-sample",
  dataset_id: "demo",
  stream_id: "tracking-1",
  layer: "silver",
  relative_path: "silver/demo/tracking/sample.parquet",
  format: "parquet",
  compression: "zstd",
  checksum_sha256: "a".repeat(64),
  row_count: 4,
  byte_size: 2048,
  artifact_kind: "sample",
  modality: "tracking",
  measurement_class: "MODEL_ESTIMATED",
  si_units: ["m"],
  coordinate_frame_id: "skillcorner-pitch-m",
  synchronization_spec_id: "skillcorner-provided",
  // The renderer sizes its window from the artifact's own canonical bounds
  // and entity cardinality, so the fixture must serve them.
  canonical_time_min_ns: 0,
  canonical_time_max_ns: 100_000_000,
  entity_column: "object_id",
  entity_count: 3,
};

const ROWS = [
  { t_rel_ns: 0, object_id: "p1", object_type: "player", group_id: "home", x_m: -5, y_m: 2, is_detected: true },
  { t_rel_ns: 0, object_id: "p2", object_type: "player", group_id: "away", x_m: 5, y_m: -2, is_detected: false },
  { t_rel_ns: 0, object_id: "ball", object_type: "ball", x_m: 0.1, y_m: 0, is_detected: true },
  { t_rel_ns: 100_000_000, object_id: "p1", object_type: "player", group_id: "home", x_m: -4, y_m: 3, is_detected: true },
];

function windowBody(reduction: unknown = null) {
  return {
    meta: {
      artifact: ARTIFACT,
      from_ns: 0,
      to_ns: 100_000_000,
      columns: ["t_rel_ns", "object_id", "object_type", "group_id", "x_m", "y_m", "is_detected"],
      source_rows: 4,
      returned_rows: 4,
      canonical_time_min_ns: 0,
      canonical_time_max_ns: 100_000_000,
      reduction,
      units: { x_m: "m", y_m: "m" },
      coordinate_frame_id: "skillcorner-pitch-m",
      measurement_class: "MODEL_ESTIMATED",
      display_note: "Exact.",
    },
    rows: ROWS,
  };
}

function installFetch(options: { reduced?: boolean; stream?: unknown } = {}): void {
  const stream = options.stream ?? STREAM;
  const session = { ...SESSION, streams: [stream] };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, "http://localhost");
      if (url.pathname === "/api/catalog/datasets/demo/sessions/s1") return json(session);
      if (url.pathname === "/api/artifacts/tracking-sample") return json(ARTIFACT);
      if (url.pathname === "/api/artifacts/tracking-sample/window") {
        return json(
          windowBody(
            options.reduced
              ? {
                  method: "min_max_envelope_per_time_bucket",
                  parameters: {},
                  source_points: 4,
                  returned_points: 2,
                  note: "display only",
                }
              : null,
          ),
        );
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

function renderPitch(overrides: Partial<AnalysisContextValue> = {}) {
  const context: AnalysisContextValue = {
    datasetId: "demo",
    sessionId: "s1",
    trialId: null,
    subjectId: null,
    timeNs: null,
    streamId: "tracking-1",
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
    ...overrides,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AnalysisContext.Provider value={context}>
        <MatchFrameContextProvider poseVisible={false}>
          <PitchReplay />
        </MatchFrameContextProvider>
      </AnalysisContext.Provider>
    </QueryClientProvider>,
  );
  return context;
}

beforeEach(() => {
  setFrame.mockClear();
  setTrail.mockClear();
  destroy.mockClear();
  createPitchRenderer.mockClear();
  setTacticalOverlay.mockClear();
  // The laboratory route owns the canonical default time (first frame).
  useAnalysisStore.setState({
    playheadNs: 0n,
    committedTimeNs: 0n,
    committedRangeNs: null,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders an exact tracking window and drives the renderer imperatively", async () => {
  installFetch();
  renderPitch();
  expect(await screen.findByTestId("pitch-canvas")).toBeInTheDocument();
  await waitFor(() => expect(createPitchRenderer).toHaveBeenCalled());
  await waitFor(() => expect(setFrame).toHaveBeenCalled());
  const call = setFrame.mock.calls[0] as
    | [TrackingWindowBuffers, number, string | null, readonly string[]]
    | undefined;
  expect(call).toBeDefined();
  const buffers = call?.[0];
  const frameIndex = call?.[1] ?? -1;
  const entities = buffers && frameIndex >= 0
    ? Array.from({ length: buffers.frameOffsets[frameIndex + 1]! - buffers.frameOffsets[frameIndex]! }, (_, offset) =>
        buffers.entityIds[buffers.entityIndexes[buffers.frameOffsets[frameIndex]! + offset]!] ?? "",
      )
    : [];
  expect(entities.sort()).toEqual(["ball", "p1", "p2"]);
  expect(call?.[2]).toBeNull();
  expect(screen.getByText(/2 players · 1 extrapolated/)).toBeInTheDocument();
  expect(screen.getByText(/Ball detected/)).toBeInTheDocument();
  // Detection state is carried by a legend with a shape cue, not by colour
  // alone, and the trail's temporal scope stays stated.
  expect(screen.getByText("Detected (filled)")).toBeInTheDocument();
  expect(screen.getByText("Extrapolated (hollow)")).toBeInTheDocument();
  expect(screen.getByText("Trails: committed range")).toBeInTheDocument();
});

it("refuses a reduced window because replay needs exact entity frames", async () => {
  installFetch({ reduced: true });
  renderPitch();
  expect(await screen.findByText("This window is display-reduced.")).toBeInTheDocument();
  expect(screen.queryByTestId("pitch-canvas")).not.toBeInTheDocument();
});

it("refuses a non-tracking stream", async () => {
  installFetch({ stream: { ...STREAM, stream_id: "pose-1", modality: "pose" } });
  renderPitch({ streamId: "pose-1" });
  expect(await screen.findByText("This stream is not 2D tracking.")).toBeInTheDocument();
});

it("requires an explicit stream and never invents one", async () => {
  installFetch();
  renderPitch({ streamId: null });
  expect(await screen.findByText("No stream selected.")).toBeInTheDocument();
});

it("keeps one renderer across playback and draws the exact frame imperatively", async () => {
  installFetch();
  renderPitch();
  await waitFor(() => expect(setFrame).toHaveBeenCalled());
  const created = createPitchRenderer.mock.calls.length;
  setFrame.mockClear();
  act(() => useAnalysisStore.getState().setPlayhead(100_000_000n));
  const call = setFrame.mock.calls.at(-1) as [TrackingWindowBuffers, number, string | null, readonly string[]];
  const start = call[0].frameOffsets[call[1]]!;
  const end = call[0].frameOffsets[call[1] + 1]!;
  expect(Array.from({ length: end - start }, (_, offset) => call[0].entityIds[call[0].entityIndexes[start + offset]!])).toEqual(["p1"]);
  // A playhead inside the same frame is not redrawn.
  setFrame.mockClear();
  act(() => useAnalysisStore.getState().setPlayhead(100_000_010n));
  expect(setFrame).not.toHaveBeenCalled();
  // RES-112 F-03: playback never rebuilds the Pixi application.
  expect(createPitchRenderer.mock.calls.length).toBe(created);
  expect(destroy).not.toHaveBeenCalled();
});

it("draws no frame for a time outside the loaded window instead of reusing its last frame", async () => {
  installFetch();
  renderPitch();
  await waitFor(() => expect(setFrame).toHaveBeenCalled());
  setFrame.mockClear();
  act(() => useAnalysisStore.getState().setPlayhead(900_000_000n));
  const call = setFrame.mock.calls.at(-1) as [TrackingWindowBuffers, number, string | null, readonly string[]];
  expect(call[1]).toBe(-1);
});

it("selects a tracked player through the shared MatchFrameContext", async () => {
  installFetch();
  const context = renderPitch({ selectSubject: vi.fn(), selectFieldEntity: vi.fn() });
  await waitFor(() => expect(createPitchRenderer).toHaveBeenCalled());
  const onSelect = createPitchRenderer.mock.calls[0]?.[2] as (objectId: string, objectType: string) => void;
  act(() => onSelect("p2", "player"));
  expect(context.selectSubject).toHaveBeenCalledWith("p2", { targetTimeNs: 0n });
  expect(context.selectFieldEntity).not.toHaveBeenCalled();
});

it("derives a session-stable team order with registered labels", () => {
  const teams = sessionTeams({
    ...SESSION,
    participants: [
      { subject_id: "a", role: "player", group_label: "871", cohort: "Perth Glory Football Club" },
      { subject_id: "b", role: "player", group_label: "1802", cohort: "Brisbane Roar FC" },
    ],
  } as never);
  expect(teams.order).toEqual(["1802", "871"]);
  expect(teams.labels.get("871")).toBe("Perth Glory Football Club");
});

it("labels pitch entities with registered shirt numbers only", () => {
  const labels = shirtLabels({
    ...SESSION,
    participants: [
      { subject_id: "p1", role: "player", group_label: "871", notes: "shirt 16 (C. Schindler)" },
      { subject_id: "p2", role: "player", group_label: "871", notes: "unregistered note" },
    ],
  } as never);
  expect(labels.get("p1")).toBe("16");
  expect(labels.has("p2")).toBe(false);
});
