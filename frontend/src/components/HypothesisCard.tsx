import { HelpCircle } from "lucide-react";
import type { Hypothesis } from "../api/types";
import ConfidenceBar from "./ConfidenceBar";
import "./HypothesisCard.css";

export default function HypothesisCard({ hypothesis }: { hypothesis: Hypothesis }) {
  return (
    <div className="hypothesis-card">
      <div className="hypothesis-head">
        <span className="hypothesis-rank mono">{hypothesis.rank}</span>
        <span className="hypothesis-title">{hypothesis.cause_display}</span>
      </div>
      <ConfidenceBar value={hypothesis.confidence} tone="warn" />
      {hypothesis.disambiguation_gap && (
        <div className="disambiguation-gap">
          <span className="gap-label">
            <HelpCircle size={11} strokeWidth={2.25} aria-hidden="true" />
            What would resolve this
          </span>
          <p>{hypothesis.disambiguation_gap}</p>
        </div>
      )}
    </div>
  );
}
