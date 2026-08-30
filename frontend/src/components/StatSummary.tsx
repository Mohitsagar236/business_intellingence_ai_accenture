import type { AnomalyStatus, MetricStatus } from "../api/types";
import "./StatSummary.css";

const GROUPS: { statuses: AnomalyStatus[]; label: (n: number) => string; tone: "ok" | "warn" | "crit" | "mute" }[] = [
  { statuses: ["validated"], label: (n) => `${n} validated`, tone: "ok" },
  { statuses: ["ambiguous"], label: (n) => `${n} ambiguous`, tone: "warn" },
  { statuses: ["suppressed_data_quality"], label: (n) => `${n} data issue${n === 1 ? "" : "s"}`, tone: "crit" },
  { statuses: ["suppressed_noise"], label: (n) => `${n} normal`, tone: "mute" },
];

export default function StatSummary({ metrics }: { metrics: MetricStatus[] }) {
  if (metrics.length === 0) return null;

  const counts = GROUPS.map((g) => ({
    ...g,
    count: metrics.filter((m) => m.latest_status && g.statuses.includes(m.latest_status)).length,
  })).filter((g) => g.count > 0);

  const checked = metrics.filter((m) => m.latest_status && m.latest_status !== "unknown").length;

  return (
    <div className="stat-summary">
      <span className="stat-total">
        {metrics.length} metric{metrics.length === 1 ? "" : "s"}
        {checked < metrics.length && <span className="stat-total-sub"> · {metrics.length - checked} not yet checked</span>}
      </span>
      {counts.length > 0 && (
        <div className="stat-chips">
          {counts.map((g) => (
            <span key={g.label(0)} className={`stat-chip stat-chip-${g.tone}`}>
              {g.label(g.count)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
