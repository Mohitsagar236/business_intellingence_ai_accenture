import type { Segment } from "../api/types";
import "./SegmentContributionChart.css";

/**
 * Horizontal bar chart of each segment's real contribution_score (the pipeline's own |z|-based
 * ranking from app/pipeline/segmentation.py) — makes visually obvious which segment is
 * actually driving the anomaly, grouped by dimension when a metric has more than one.
 */
export default function SegmentContributionChart({ segments }: { segments: Segment[] }) {
  if (segments.length === 0) return null;

  const byDimension = new Map<string, Segment[]>();
  for (const s of segments) {
    const list = byDimension.get(s.dimension) ?? [];
    list.push(s);
    byDimension.set(s.dimension, list);
  }

  return (
    <div className="segment-chart">
      {[...byDimension.entries()].map(([dimension, rows]) => {
        const max = Math.max(...rows.map((r) => r.contribution_score), 1e-6);
        const sorted = [...rows].sort((a, b) => b.contribution_score - a.contribution_score);
        return (
          <div className="segment-chart-group" key={dimension}>
            <div className="segment-chart-dim mono">{dimension}</div>
            {sorted.map((s) => (
              <div className={`segment-chart-row ${s.is_primary ? "is-primary" : ""}`} key={s.value}>
                <span className="segment-chart-label">{s.value}</span>
                <div className="segment-chart-track">
                  <div className="segment-chart-fill" style={{ width: `${Math.max(4, (s.contribution_score / max) * 100)}%` }} />
                </div>
                <span className="segment-chart-score mono">{s.contribution_score.toFixed(2)}</span>
                {s.is_primary && <span className="segment-chart-badge">Primary</span>}
              </div>
            ))}
          </div>
        );
      })}
      <p className="segment-chart-note">Bars show each segment's contribution score (|z| of its own deviation) — the pipeline's actual ranking, not a fabricated percentage.</p>
    </div>
  );
}
