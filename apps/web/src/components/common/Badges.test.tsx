import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  MeasurementClassBadge,
  ModalityBadge,
  QualityBadge,
} from "@/components/common/Badges";
import { MEASUREMENT_CLASSES } from "@/lib/measurement";

describe("measurement class badge", () => {
  it("carries text and a shape in addition to color", () => {
    render(<MeasurementClassBadge measurementClass="MODEL_ESTIMATED" />);
    const text = screen.getByText("Model-estimated");
    expect(text).toBeInTheDocument();
    const shape = text.parentElement?.querySelector("[data-shape]");
    expect(shape).toHaveAttribute("data-shape", "triangle");
  });

  it("exposes the scientific boundary in its title", () => {
    render(<MeasurementClassBadge measurementClass="SOURCE_DERIVED" compact />);
    const badge = screen.getByTitle(/Source-derived reference/);
    expect(badge).toBeInTheDocument();
    expect(badge.getAttribute("title")).toContain("Computed by the source/provider");
  });

  it("falls back to an explicit unclassified label", () => {
    render(<MeasurementClassBadge measurementClass="" />);
    expect(screen.getByText("unclassified")).toBeInTheDocument();
  });

  it("keeps every class distinct by shape", () => {
    const shapes = new Set<string>();
    for (const descriptor of Object.values(MEASUREMENT_CLASSES)) {
      const { container } = render(
        <MeasurementClassBadge measurementClass={descriptor.id} compact />,
      );
      const shape = container.querySelector("[data-shape]");
      expect(shape).not.toBeNull();
      shapes.add(shape?.getAttribute("data-shape") ?? "");
    }
    expect(shapes.size).toBe(4);
  });
});

describe("quality badge", () => {
  it("renders a glyph and a label, not only a color", () => {
    render(<QualityBadge state="quarantined" label="ERROR" />);
    expect(screen.getByText("■")).toBeInTheDocument();
    expect(screen.getByText("ERROR")).toBeInTheDocument();
  });
});

describe("modality badge", () => {
  it("renders the modality name as text", () => {
    render(<ModalityBadge modality="pose" />);
    expect(screen.getByText("pose")).toBeInTheDocument();
  });
});
