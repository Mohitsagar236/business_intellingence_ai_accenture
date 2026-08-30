import type { AnomalyDetail } from "../api/types";
import "./EvidenceTimeline.css";

interface Row {
  label: string;
  start: string;
  end: string;
  kind: "anomaly" | "structured" | "unstructured";
  evidenceId?: number;
}

function daysBetween(a: string, b: string): number {
  return (new Date(b).getTime() - new Date(a).getTime()) / 86_400_000;
}

/**
 * Shared-axis timeline showing the KPI anomaly window alongside each piece of evidence's own
 * real date window (app/api/anomalies.py computes these from the actual lag_days shift and
 * the actual referenced TextEvidence timestamps — never invented here) — makes temporal
 * convergence visually obvious instead of just implied by matching text.
 */
export default function EvidenceTimeline({ anomaly }: { anomaly: AnomalyDetail }) {
  const rows: Row[] = [{ label: `${anomaly.metric.name} anomaly`, start: anomaly.window_start, end: anomaly.window_end, kind: "anomaly" }];

  for (const e of anomaly.evidence) {
    if (!e.window_start || !e.window_end) continue;
    rows.push({
      label: e.type === "structured" ? e.source : `Theme: ${e.theme_keywords?.slice(0, 2).join(", ") ?? "text spike"}`,
      start: e.window_start,
      end: e.window_end,
      kind: e.type,
      evidenceId: e.id,
    });
  }

  if (rows.length <= 1) return null;

  const allDates = rows.flatMap((r) => [r.start, r.end]);
  const minDate = allDates.reduce((a, b) => (a < b ? a : b));
  const maxDate = allDates.reduce((a, b) => (a > b ? a : b));
  const totalSpan = Math.max(1, daysBetween(minDate, maxDate));

  return (
    <div className="evidence-timeline">
      {rows.map((r) => {
        const left = (daysBetween(minDate, r.start) / totalSpan) * 100;
        const width = Math.max(1.5, (daysBetween(r.start, r.end) / totalSpan) * 100);
        return (
          <div className="evidence-timeline-row" key={r.label + r.start}>
            {r.evidenceId ? (
              <a className="evidence-timeline-label evidence-timeline-link" href={`#evidence-${r.evidenceId}`}>
                {r.label}
              </a>
            ) : (
              <span className="evidence-timeline-label">{r.label}</span>
            )}
            <div className="evidence-timeline-track">
              <div className={`evidence-timeline-bar bar-${r.kind}`} style={{ left: `${left}%`, width: `${width}%` }} title={`${r.start} → ${r.end}`} />
            </div>
            <span className="evidence-timeline-dates mono">
              {r.start} → {r.end}
            </span>
          </div>
        );
      })}
    </div>
  );
}
