import { BarChart3, MessageSquareText, ShieldQuestion } from "lucide-react";
import type { AnomalyDetail, Evidence } from "../api/types";
import StatusPill from "./StatusPill";
import ConfidenceBar from "./ConfidenceBar";
import "./RootCauseChain.css";

function findEvidence(evidence: Evidence[], id: number | null | undefined): Evidence | undefined {
  if (id === null || id === undefined) return undefined;
  return evidence.find((e) => e.id === id);
}

function EvidenceNode({ evidence, kind }: { evidence: Evidence | undefined; kind: "structured" | "unstructured" }) {
  const icon = kind === "structured" ? <BarChart3 size={14} strokeWidth={2.25} aria-hidden="true" /> : <MessageSquareText size={14} strokeWidth={2.25} aria-hidden="true" />;
  const title = kind === "structured" ? "Structured Signal" : "Text Theme Spike";

  if (!evidence) {
    return (
      <div className="chain-node chain-node-empty">
        <span className="chain-node-icon">{icon}</span>
        <span className="chain-node-title">{title}</span>
        <span className="chain-node-detail">None found in this segment/window</span>
      </div>
    );
  }
  return (
    <a className="chain-node chain-node-evidence" href={`#evidence-${evidence.id}`}>
      <span className="chain-node-icon">{icon}</span>
      <span className="chain-node-title">{title}</span>
      <span className="chain-node-detail">{evidence.description}</span>
    </a>
  );
}

/**
 * The visual evidence chain — KPI anomaly → affected segment → (structured signal + text
 * theme, converging) → hypothesis → recommendation for a validated cause, or a branching
 * "multiple hypotheses" layout for an ambiguous one. Every node reads directly off the real
 * anomaly/evidence/hypothesis data already returned by GET /api/anomalies/{id} — nothing here
 * is laid out to imply more certainty than the backend's own status says.
 */
export default function RootCauseChain({ anomaly }: { anomaly: AnomalyDetail }) {
  const primarySegments = anomaly.segments.filter((s) => s.is_primary);
  const hypotheses = [...anomaly.hypotheses].sort((a, b) => a.rank - b.rank);
  const isValidated = anomaly.status === "validated";
  const isSuppressed = anomaly.status.startsWith("suppressed");
  const top = hypotheses[0];

  if (isSuppressed) {
    return (
      <div className="root-cause-chain">
        <div className="chain-node chain-node-anomaly">
          <StatusPill status={anomaly.status} />
          <span className="chain-node-title">{anomaly.metric.name}</span>
        </div>
        <div className="chain-arrow" aria-hidden="true" />
        <div className="chain-node chain-node-suppressed">
          <ShieldQuestion size={14} strokeWidth={2.25} aria-hidden="true" />
          <span className="chain-node-detail">
            Suppressed before root-cause analysis ran — this was logged as normal variation or a data-quality issue, not a
            finding. No cause is asserted.
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="root-cause-chain">
      <div className="chain-node chain-node-anomaly">
        <StatusPill status={anomaly.status} />
        <span className="chain-node-title">{anomaly.metric.name}</span>
        <span className="chain-node-detail mono">
          {anomaly.magnitude_pct >= 0 ? "+" : ""}
          {anomaly.magnitude_pct.toFixed(1)}%
        </span>
      </div>
      <div className="chain-arrow" aria-hidden="true" />

      <div className="chain-node chain-node-segment">
        <span className="chain-node-title">Affected Segment</span>
        <span className="chain-node-detail">
          {primarySegments.length > 0 ? primarySegments.map((s) => `${s.dimension}=${s.value}`).join(", ") : "No dominant segment isolated"}
        </span>
      </div>
      <div className="chain-arrow" aria-hidden="true" />

      {isValidated && top ? (
        <>
          <div className="chain-converge">
            <EvidenceNode evidence={findEvidence(anomaly.evidence, top.structured_evidence_id)} kind="structured" />
            <EvidenceNode evidence={findEvidence(anomaly.evidence, top.unstructured_evidence_id)} kind="unstructured" />
          </div>
          <div className="chain-arrow" aria-hidden="true" />

          <div className="chain-node chain-node-hypothesis chain-node-validated">
            <StatusPill status="validated" />
            <span className="chain-node-title">{top.cause_display}</span>
            <ConfidenceBar value={top.confidence} tone="accent" />
          </div>
          <div className="chain-arrow" aria-hidden="true" />

          <div className="chain-node chain-node-recommendation">
            <span className="chain-node-title">Recommendation</span>
            <span className="chain-node-detail">{anomaly.report?.action_statement}</span>
          </div>
        </>
      ) : (
        <>
          <div className="chain-node chain-node-branch-label">
            <StatusPill status="ambiguous" />
            <span className="chain-node-detail">Evidence does not converge on a single cause — every surviving explanation is kept and ranked.</span>
          </div>

          <div className="chain-branches">
            {hypotheses.map((h) => (
              <div className="chain-branch" key={h.id}>
                <div className="chain-node chain-node-hypothesis chain-node-candidate">
                  <span className="chain-node-title">{h.cause_display}</span>
                  <ConfidenceBar value={h.confidence} tone="warn" />
                </div>
                {(h.structured_evidence_id || h.unstructured_evidence_id) && (
                  <div className="chain-branch-evidence">
                    {h.structured_evidence_id && <EvidenceNode evidence={findEvidence(anomaly.evidence, h.structured_evidence_id)} kind="structured" />}
                    {h.unstructured_evidence_id && <EvidenceNode evidence={findEvidence(anomaly.evidence, h.unstructured_evidence_id)} kind="unstructured" />}
                  </div>
                )}
                {h.disambiguation_gap && (
                  <div className="chain-node chain-node-gap">
                    <span className="chain-node-title">Evidence gap</span>
                    <span className="chain-node-detail">{h.disambiguation_gap}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
