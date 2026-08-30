import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ChevronRight, Inbox, Play, UploadCloud } from "lucide-react";
import { useMetricDetail, useRunDetection } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { CAN_RUN_DETECTION } from "../auth/types";
import StatusPill, { STATUS_LABELS } from "../components/StatusPill";
import TimeSeriesChart from "../components/TimeSeriesChart";
import "./MetricDetail.css";

export default function MetricDetail() {
  const { metricId } = useParams();
  const id = Number(metricId);
  const { data: metric, isLoading } = useMetricDetail(id);
  const runDetection = useRunDetection(id);
  const { user } = useAuth();
  const canRun = !!user && CAN_RUN_DETECTION.includes(user.role);

  if (isLoading || !metric) {
    return (
      <div className="metric-detail">
        <div className="skeleton" style={{ width: 120, height: 22, marginBottom: 22, borderRadius: 6 }} />
        <div className="card chart-card">
          <div className="skeleton" style={{ height: 280, borderRadius: 8 }} />
        </div>
      </div>
    );
  }

  const latest = metric.anomalies[0];

  return (
    <div className="metric-detail">
      <Link to="/" className="back-link">
        <ArrowLeft size={13} strokeWidth={2.25} aria-hidden="true" />
        Dashboard
      </Link>

      <div className="page-head">
        <div className="kicker">{metric.department}</div>
        <h1>{metric.name}</h1>
        <p className="page-sub">
          Aggregation: <span className="mono">{metric.aggregation}</span> · Unit: <span className="mono">{metric.unit}</span>
        </p>
      </div>

      <div className="card chart-card">
        <div className="chart-card-head">
          <StatusPill status={metric.latest_status} />
          {canRun && (
            <button className="btn-run btn-run-lg" onClick={() => runDetection.mutate()} disabled={runDetection.isPending}>
              <Play size={13} strokeWidth={2.25} aria-hidden="true" />
              {runDetection.isPending ? "Running…" : "Run detection on latest window"}
            </button>
          )}
        </div>
        {runDetection.isError && (
          <div className="run-feedback run-feedback-error" style={{ marginBottom: 16 }}>
            Detection failed: {(runDetection.error as Error).message}
          </div>
        )}
        {!runDetection.isError && runDetection.data && (
          <div className="run-feedback run-feedback-ok" style={{ marginBottom: 16 }}>
            Ran just now → {STATUS_LABELS[runDetection.data.status] ?? runDetection.data.status}
          </div>
        )}
        {metric.observation_count === 0 ? (
          <div className="empty-block">
            <Inbox size={22} strokeWidth={1.75} aria-hidden="true" />
            <p>No observations uploaded yet.</p>
            {user?.role === "admin" && (
              <Link to="/data" className="btn-run">
                <UploadCloud size={13} strokeWidth={2.25} aria-hidden="true" />
                Upload data
              </Link>
            )}
          </div>
        ) : (
          <>
            {metric.insufficient_history && (
              <div className="run-feedback run-feedback-ok" style={{ marginBottom: 12 }}>
                Only {metric.observation_count} day(s) of history — trend/seasonal decomposition needs at least{" "}
                {2 * metric.seasonality_period} to kick in. Values below are raw until then.
              </div>
            )}
            <TimeSeriesChart series={metric.series} highlightStart={latest?.window_start} highlightEnd={latest?.window_end} />
          </>
        )}
      </div>

      <div className="anomaly-history">
        <h2>Anomaly history</h2>
        {metric.anomalies.length === 0 && <div className="state-msg">No anomalies detected yet for this metric.</div>}
        <div className="anomaly-list">
          {metric.anomalies.map((a) => (
            <Link to={`/anomalies/${a.id}`} key={a.id} className="anomaly-row card card-hover">
              <div className="anomaly-row-window mono">
                {a.window_start} → {a.window_end}
              </div>
              <div className="anomaly-row-mag mono">{a.magnitude_pct >= 0 ? "+" : ""}{a.magnitude_pct.toFixed(1)}%</div>
              <div className="anomaly-row-z mono">z={a.significance_score.toFixed(2)}</div>
              <StatusPill status={a.status} />
              <ChevronRight size={15} strokeWidth={2} className="anomaly-row-chevron" aria-hidden="true" />
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
