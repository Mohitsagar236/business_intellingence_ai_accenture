import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatusPill from "./StatusPill";

describe("StatusPill", () => {
  it("labels a validated anomaly as Validated", () => {
    render(<StatusPill status="validated" />);
    expect(screen.getByText("Validated")).toBeInTheDocument();
  });

  it("labels an ambiguous anomaly as Ambiguous, never as a false certainty", () => {
    render(<StatusPill status="ambiguous" />);
    expect(screen.getByText("Ambiguous")).toBeInTheDocument();
  });

  it("labels a data-quality suppression distinctly from a noise suppression", () => {
    const { rerender } = render(<StatusPill status="suppressed_data_quality" />);
    expect(screen.getByText("Data quality issue")).toBeInTheDocument();
    rerender(<StatusPill status="suppressed_noise" />);
    expect(screen.getByText("Normal variation")).toBeInTheDocument();
  });

  it("falls back to 'Not yet checked' for null/undefined rather than crashing", () => {
    render(<StatusPill status={null} />);
    expect(screen.getByText("Not yet checked")).toBeInTheDocument();
  });
});
