import { BarChart3, Layers, MessageSquareText } from "lucide-react";
import type { Evidence } from "../api/types";
import "./EvidencePanel.css";

export default function EvidencePanel({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null;

  return (
    <div className="evidence-panel">
      <h3>
        <Layers size={15} strokeWidth={2.25} aria-hidden="true" />
        Evidence
      </h3>
      <div className="evidence-list">
        {evidence.map((e) => (
          <div className="evidence-card" id={`evidence-${e.id}`} key={e.id}>
            <div className="evidence-head">
              <span className="evidence-id mono">E{e.id}</span>
              <span className={`evidence-type-badge type-${e.type}`}>
                {e.type === "structured" ? <BarChart3 size={11} strokeWidth={2.25} aria-hidden="true" /> : <MessageSquareText size={11} strokeWidth={2.25} aria-hidden="true" />}
                {e.type === "structured" ? "Structured" : "Unstructured"}
              </span>
              <span className="evidence-source mono">{e.source}</span>
            </div>
            <p className="evidence-desc">{e.description}</p>
            {e.type === "structured" && e.correlation !== null && (
              <div className="evidence-stats mono">
                r = {e.correlation.toFixed(2)} · lag = {e.lag_days}d
              </div>
            )}
            {e.theme_keywords && (
              <div className="evidence-keywords">
                {e.theme_keywords.slice(0, 6).map((k) => (
                  <span key={k} className="keyword-chip">
                    {k}
                  </span>
                ))}
              </div>
            )}
            {e.excerpts.length > 0 && (
              <ul className="evidence-excerpts">
                {[...new Set(e.excerpts)].slice(0, 3).map((ex, i) => (
                  <li key={i}>"{ex}"</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
