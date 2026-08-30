import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EvidencePanel from "./EvidencePanel";
import type { Evidence } from "../api/types";

function makeEvidence(overrides: Partial<Evidence> = {}): Evidence {
  return {
    id: 1,
    type: "unstructured",
    source: "ticketing",
    description: "Theme detected",
    correlation: null,
    lag_days: null,
    theme_keywords: null,
    spike_ratio: null,
    excerpts: [],
    window_start: null,
    window_end: null,
    ...overrides,
  };
}

describe("EvidencePanel", () => {
  it("renders nothing when there is no evidence", () => {
    const { container } = render(<EvidencePanel evidence={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("gives each evidence card a stable anchor id matching its citation chip target", () => {
    render(<EvidencePanel evidence={[makeEvidence({ id: 5 })]} />);
    expect(document.getElementById("evidence-5")).toBeInTheDocument();
  });

  it("deduplicates repeated excerpts so the same quote isn't shown three times", () => {
    const evidence = makeEvidence({
      excerpts: ["Card charged but payment failed.", "Card charged but payment failed.", "Different ticket entirely."],
    });
    render(<EvidencePanel evidence={[evidence]} />);
    expect(screen.getAllByText(/Card charged but payment failed\./)).toHaveLength(1);
    expect(screen.getByText(/Different ticket entirely\./)).toBeInTheDocument();
  });

  it("shows correlation stats only for structured evidence", () => {
    render(<EvidencePanel evidence={[makeEvidence({ type: "structured", correlation: -0.64, lag_days: 0 })]} />);
    expect(screen.getByText(/r = -0.64/)).toBeInTheDocument();
  });
});
