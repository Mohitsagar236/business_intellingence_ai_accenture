import { Link } from "react-router-dom";
import type { MetricStatus, SeriesPoint } from "../api/types";
import StatusPill, { STATUS_LABELS } from "./StatusPill";
import Sparkline from "./Sparkline";
import { departmentIcon } from "./departmentIcon";
import "./KpiCard.css";

const TONE: Record<string, "accent" | "ok" | "warn" | "crit"> = {
  validated: "crit",
  ambiguous: "warn",
  suppressed_noise: "ok",
  suppressed_data_quality: "crit",
};

export default function KpiCard({
  metric,
  series,
  onRunDetection,
  isRunning,
  canRun,
  lastResultStatus,
  lastError,
}: {
  metric: MetricStatus;
  series: SeriesPoint[] | undefined;
  onRunDetection: () => void;
  isRunning: boolean;
  canRun: boolean;
  lastResultStatus?: string;
  lastError?: string;
}) {
  const tone = TONE[metric.latest_status ?? ""] ?? "accent";
  const DeptIcon = departmentIcon(metric.department);

  return (
    <div className="kpi-card">
      <div className="kpi-card-head">
        <div className="kpi-title-group">
          <div className="kpi-dept">
            <DeptIcon size={12} strokeWidth={2.25} aria-hidden="true" />
            {metric.department}
          </div>
          <Link to={`/metrics/${metric.id}`} className="kpi-name">
            {metric.name}
          </Link>
        </div>
        <StatusPill status={metric.latest_status} />
      </div>

      <div className="kpi-spark">{series ? <Sparkline series={series} tone={tone} /> : <div className="kpi-spark-empty" />}</div>

      <div className="kpi-card-foot">
        <span className="kpi-unit mono">unit: {metric.unit}</span>
        {canRun && (
          <button className="btn-run" onClick={onRunDetection} disabled={isRunning}>
            {isRunning ? "Running…" : "Run detection"}
          </button>
        )}
      </div>

      {lastError && <div className="run-feedback run-feedback-error">Detection failed: {lastError}</div>}
      {!lastError && lastResultStatus && (
        <div className="run-feedback run-feedback-ok">
          Ran just now → {STATUS_LABELS[lastResultStatus] ?? lastResultStatus}
        </div>
      )}
    </div>
  );
}
