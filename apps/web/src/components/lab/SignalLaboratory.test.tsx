import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { tableFromArrays, tableToIPC } from "apache-arrow";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { SignalLaboratory } from "@/components/lab/SignalLaboratory";
import { AnalysisContext, type AnalysisContextValue } from "@/lib/analysis-context";

vi.mock("uplot", () => ({
  default: class MockUPlot {
    readonly over: HTMLDivElement;
    readonly cursor = { left: 0 };
    readonly select = { left: 0, top: 0, width: 0, height: 0 };
    readonly height = 320;

    constructor(_options: unknown, _data: unknown, target: HTMLElement) {
      this.over = document.createElement("div");
      target.append(this.over);
    }

    destroy() {
      this.over.remove();
    }

    setSize() {}
    setCursor() {}
    setScale() {}
    setSelect() {}
    posToVal(position: number) {
      return position;
    }
    valToPos(value: number) {
      return value;
    }
  },
}));

const SESSION = {
  dataset_id: "demo",
  session: {
    session_id: "s1",
    kind: "laboratory",
    label: null,
    started_at: null,
    ended_at: null,
    participant_count: 1,
    trial_count: 0,
    stream_count: 1,
  },
  participants: [],
  trials: [],
  streams: [
    {
      stream_id: "lpt-1",
      modality: "lpt",
      measurement_class: "RAW_MEASURED",
      subject_id: null,
      trial_id: null,
      device_id: null,
      nominal_sampling_rate_hz: 100,
      si_units: ["m"],
      source_unit: "m",
      coordinate_frame_id: "lab-frame",
      synchronization_spec_id: "source-provided",
      clock_id: "clock-1",
      skeleton_id: null,
      sample_artifact_ids: ["sample-1"],
      sample_row_count: 3,
    },
  ],
};

const ARTIFACT = {
  artifact_id: "sample-1",
  dataset_id: "demo",
  stream_id: "lpt-1",
  layer: "silver",
  relative_path: "silver/demo/lpt/sample-1.parquet",
  format: "parquet",
  compression: "zstd",
  checksum_sha256: "a".repeat(64),
  row_count: 3,
  byte_size: 1024,
  artifact_kind: "sample",
  modality: "lpt",
  measurement_class: "RAW_MEASURED",
  si_units: ["m"],
  coordinate_frame_id: "lab-frame",
  synchronization_spec_id: "source-provided",
  entity_column: "subject_id",
  entity_count: 2,
  entity_ids: ["s1", "s2"],
};

function windowBody(reduced: boolean) {
  return {
    meta: {
      artifact: ARTIFACT,
      from_ns: 0,
      to_ns: 20_000_000,
      columns: reduced ? ["t_rel_ns", "x_m_min", "x_m_max"] : ["t_rel_ns", "x_m"],
      source_rows: 3,
      returned_rows: reduced ? 2 : 3,
      canonical_time_min_ns: 0,
      canonical_time_max_ns: 20_000_000,
      reduction: reduced
        ? {
            method: "min_max_envelope_per_time_bucket",
            parameters: {},
            source_points: 3,
            returned_points: 2,
            note: "display only",
          }
        : null,
      units: { x_m: "m" },
      coordinate_frame_id: "lab-frame",
      measurement_class: "RAW_MEASURED",
      display_note: reduced ? "Display-reduced." : "Exact.",
    },
    rows: reduced
      ? [
          { t_rel_ns: 0, x_m_min: 0, x_m_max: 1 },
          { t_rel_ns: 10_000_000, x_m_min: 1, x_m_max: 2 },
        ]
      : [
          { t_rel_ns: 0, x_m: 0 },
          { t_rel_ns: 10_000_000, x_m: 1 },
          { t_rel_ns: 20_000_000, x_m: 2 },
        ],
  };
}

function windowBodyForSubject(subjectId: string) {
  const body = windowBody(false);
  const exactRows = body.rows.filter(
    (row): row is { t_rel_ns: number; x_m: number } => "x_m" in row,
  );
  return {
    ...body,
    rows: exactRows.map((row) => ({
      ...row,
      subject_id: subjectId,
      x_m: subjectId === "s2" ? 20 : row.x_m,
    })),
    meta: {
      ...body.meta,
      columns: ["t_rel_ns", "subject_id", "x_m"],
    },
  };
}

function arrowWindowResponse(): Response {
  const table = tableFromArrays({
    t_rel_ns: BigInt64Array.from([0n, 10_000_000n, 20_000_000n]),
    subject_id: ["s1", "s1", "s1"],
    x_m: Float64Array.from([0, 1, 2]),
  });
  const ipc = tableToIPC(table, "stream");
  const buffer = ipc.buffer.slice(ipc.byteOffset, ipc.byteOffset + ipc.byteLength) as ArrayBuffer;
  return new Response(buffer, {
    status: 200,
    headers: {
      "Content-Type": "application/vnd.apache.arrow.stream",
      "X-Dynamis-Window-Meta": JSON.stringify(windowBody(false).meta),
    },
  });
}

function installFetch(reduced = false, windowStatus = 200, arrow = false): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const url = new URL(raw, "http://localhost");
      if (url.pathname === "/api/catalog/datasets/demo/sessions/s1") {
        return json(SESSION);
      }
      if (url.pathname === "/api/artifacts/sample-1") {
        return json(ARTIFACT);
      }
      if (url.pathname === "/api/artifacts/sample-1/window") {
        if (arrow && url.searchParams.get("format") === "arrow") {
          return arrowWindowResponse();
        }
        if (windowStatus !== 200) {
          return json({ detail: "too large", state: "dense_window_too_large" }, windowStatus);
        }
        return json(
          reduced
            ? windowBody(reduced)
            : url.searchParams.has("entity_id")
            ? windowBodyForSubject(url.searchParams.get("entity_id") ?? "")
            : windowBody(reduced),
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

function renderLab(overrides: Partial<AnalysisContextValue> = {}) {
  const context: AnalysisContextValue = {
    datasetId: "demo",
    sessionId: "s1",
    trialId: null,
    subjectId: null,
    streamId: "lpt-1",
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
        <SignalLaboratory />
      </AnalysisContext.Provider>
    </QueryClientProvider>,
  );
  return context;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders an exact window with unit, synchronization and measurement context", async () => {
  installFetch(false);
  renderLab();
  expect(await screen.findByText("Exact samples")).toBeInTheDocument();
  expect(screen.getByText("3 source rows → 3 plotted")).toBeInTheDocument();
  expect(screen.getByText("source-provided")).toBeInTheDocument();
  expect(screen.getByText("lab-frame")).toBeInTheDocument();
  expect(screen.getByText("raw")).toBeInTheDocument();
  expect(await screen.findByTestId("uplot")).toBeInTheDocument();
});

it("states display reduction and never hides it", async () => {
  installFetch(true);
  renderLab();
  // The state is a badge; the full reduction record stays available on it,
  // and the envelope is named as display reduction rather than uncertainty.
  expect(await screen.findByText("Display-reduced")).toBeInTheDocument();
  expect(
    screen.getByTitle(/Display-reduced: min_max_envelope_per_time_bucket/),
  ).toBeInTheDocument();
  expect(screen.getByText(/not measured uncertainty/)).toBeInTheDocument();
  expect(screen.getByText(/never derive from it/)).toBeInTheDocument();
});

it("asks for a narrower range when the dense window is too large", async () => {
  installFetch(false, 413);
  renderLab();
  expect(await screen.findByText("Dense window too large.")).toBeInTheDocument();
  expect(screen.getByText(/Narrow the time range/)).toBeInTheDocument();
});

it("requires an explicit stream and never invents one", async () => {
  installFetch(false);
  renderLab({ streamId: null });
  expect(await screen.findByText("No stream selected.")).toBeInTheDocument();
});

it("refuses a stream that is not part of the open session", async () => {
  installFetch(false);
  renderLab({ streamId: "other-stream" });
  expect(await screen.findByText("Stream is not part of this session.")).toBeInTheDocument();
});

it("uses the Arrow dense transport when the API serves it", async () => {
  installFetch(false, 200, true);
  renderLab();
  expect(await screen.findByText("arrow transport")).toBeInTheDocument();
  expect(await screen.findByTestId("uplot")).toBeInTheDocument();
  expect(screen.getByText("3 source rows → 3 plotted")).toBeInTheDocument();
});

it("shows the selected individual and scopes the signal rows to it", async () => {
  const fetchSpy = vi.fn();
  installFetch(false);
  fetchSpy.mockImplementation(globalThis.fetch);
  vi.stubGlobal("fetch", fetchSpy);
  renderLab({ subjectId: "s2" });

  expect(await screen.findByDisplayValue("s2")).toBeInTheDocument();
  expect(screen.getByText("selected identity scopes the dense request and evidence")).toBeInTheDocument();
  await vi.waitFor(() => {
    const urls = fetchSpy.mock.calls.map(([input]) =>
      new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost"),
    );
    expect(
      urls.some(
        (url) =>
          url.pathname === "/api/artifacts/sample-1/window" &&
          url.searchParams.get("entity_id") === "s2",
      ),
    ).toBe(true);
  });
});
