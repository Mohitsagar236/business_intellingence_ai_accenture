import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ConfidenceBar from "./ConfidenceBar";

describe("ConfidenceBar", () => {
  it("renders a fractional confidence as a rounded percentage", () => {
    render(<ConfidenceBar value={0.8} />);
    expect(screen.getByText("80%")).toBeInTheDocument();
  });

  it("rounds rather than truncates", () => {
    render(<ConfidenceBar value={0.545} />);
    expect(screen.getByText("55%")).toBeInTheDocument();
  });

  it("sets the fill width proportionally to the confidence value", () => {
    const { container } = render(<ConfidenceBar value={0.43} />);
    const fill = container.querySelector(".confidence-fill") as HTMLElement;
    expect(fill.style.width).toBe("43%");
  });
});
