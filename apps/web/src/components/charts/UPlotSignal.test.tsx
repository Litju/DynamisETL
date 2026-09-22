import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UPlotSignal, type UPlotSignalProps } from "@/components/charts/UPlotSignal";
import { useAnalysisStore } from "@/lib/state/analysis";

const captured = vi.hoisted(() => ({
  plots: [] as Array<{ options: unknown; data: unknown; instance: unknown }>,
}));

vi.mock("uplot", () => ({
  default: class MockUPlot {
    readonly over = document.createElement("div");
    readonly cursor = { left: 0 };
    readonly height = 320;
    readonly select = { left: 0, top: 0, width: 0, height: 0 };
    width = 640;

    constructor(options: unknown, data: unknown, target: HTMLElement) {
      target.append(this.over);
      captured.plots.push({ options, data, instance: this });
    }

    setSize(size: { width: number }) {
      this.width = size.width;
    }

    setSelect(selection: { left: number; top: number; width: number; height: number }) {
      Object.assign(this.select, selection);
    }

    posToVal(position: number) {
      return position;
    }

    valToPos(value: number) {
      return value * (this.width / 640);
    }

    destroy() {
      this.over.remove();
    }
  },
}));

let resize: ResizeObserverCallback | null = null;

class TestResizeObserver implements ResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resize = callback;
  }

  observe() {}
  unobserve() {}
  disconnect() {}
}

function renderSignal(overrides: Partial<UPlotSignalProps> = {}) {
  return render(
    <UPlotSignal
      ariaLabel="Force trace"
      panes={[{ id: "force", label: "Force", unit: "N" }]}
      series={[{
        name: "Force",
        unit: "N",
        measurementClass: "RAW_MEASURED",
        paneIndex: 0,
        points: [[0, 1], [1_000, null], [2_000, 3]],
      }]}
      bands={[]}
      originNs={0n}
      playheadMs={500}
      rangeMs={{ fromMs: 100, toMs: 300 }}
      {...overrides}
    />,
  );
}

beforeEach(() => {
  captured.plots.length = 0;
  resize = null;
  useAnalysisStore.setState({ playheadNs: null, committedTimeNs: null });
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UPlotSignal", () => {
  it("passes explicit null gaps and initializes replacement plots from current state", async () => {
    const view = renderSignal();
    await waitFor(() => expect(captured.plots).toHaveLength(1));
    expect(captured.plots[0]?.data).toEqual([[0, 1_000, 2_000], [1, null, 3]]);

    view.rerender(
      <UPlotSignal
        ariaLabel="Force trace"
        panes={[{ id: "force", label: "Force", unit: "N" }]}
        series={[{
          name: "Force",
          unit: "N",
          measurementClass: "RAW_MEASURED",
          paneIndex: 0,
          points: [[10_000, 1], [11_000, 3]],
        }]}
        bands={[]}
        originNs={0n}
        playheadMs={10_500}
        rangeMs={{ fromMs: 10_200, toMs: 10_800 }}
      />,
    );
    await waitFor(() => expect(captured.plots).toHaveLength(2));
    const host = screen.getByTestId("uplot");
    await waitFor(() => expect(host).toHaveAttribute("data-renderer-ready", "true"));
    expect(host.querySelector(".uplot-signal__playhead")?.getAttribute("style")).toContain("left: 10500px");
    const replacement = captured.plots[1]?.instance as {
      readonly select: { readonly left: number; readonly width: number };
    };
    expect(replacement.select).toMatchObject({ left: 10_200, width: 600 });
  });

  it("repositions the playhead after resizing while paused", async () => {
    renderSignal({ playheadMs: 500, rangeMs: null });
    await waitFor(() => expect(captured.plots).toHaveLength(1));
    const playhead = screen.getByTestId("uplot").querySelector(".uplot-signal__playhead");
    expect(playhead?.getAttribute("style")).toContain("left: 500px");
    const instance = captured.plots[0]?.instance as ResizeObserver;
    resize?.([], instance);
    expect(playhead?.getAttribute("style")).toContain("left: 250px");
  });

  it("supports keyboard range selection and point navigation", async () => {
    const onRangeZoom = vi.fn();
    const onPointClick = vi.fn();
    renderSignal({ onRangeZoom, onPointClick });
    const chart = screen.getByTestId("uplot");
    await waitFor(() => expect(captured.plots).toHaveLength(1));

    fireEvent.keyDown(chart, { key: "ArrowRight", shiftKey: true });
    expect(onRangeZoom).toHaveBeenCalledWith({ fromMs: 0, toMs: 2 });
    fireEvent.keyUp(chart, { key: "Shift" });
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(onPointClick).toHaveBeenCalledWith({ xMs: 2 });
    expect(chart).toHaveAttribute("aria-description", expect.stringContaining("Shift with an arrow key"));
  });
});
