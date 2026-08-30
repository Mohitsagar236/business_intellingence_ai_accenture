import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CitedText from "./CitedText";

describe("CitedText", () => {
  it("renders plain text with no citations unchanged", () => {
    render(<CitedText text="No claims here." />);
    expect(screen.getByText("No claims here.")).toBeInTheDocument();
  });

  it("renders a citation marker as a clickable chip pointing at the evidence anchor", () => {
    render(<CitedText text="Revenue dropped [E1] in the affected segment." />);
    const chip = screen.getByRole("link", { name: "E1" });
    expect(chip).toHaveAttribute("href", "#evidence-1");
  });

  it("renders multiple distinct citations in one sentence as separate chips", () => {
    render(<CitedText text="Together this converges on the cause [E3][E7]." />);
    expect(screen.getByRole("link", { name: "E3" })).toHaveAttribute("href", "#evidence-3");
    expect(screen.getByRole("link", { name: "E7" })).toHaveAttribute("href", "#evidence-7");
  });

  it("preserves surrounding text around a citation", () => {
    const { container } = render(<CitedText text="Payment failures spiked [E2] across the region." />);
    expect(container.textContent).toBe("Payment failures spiked E2 across the region.");
  });
});
