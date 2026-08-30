import { Link } from "react-router-dom";
import { Database, LayoutGrid } from "lucide-react";
import { useMetricDetail, useMetrics, useRunDetection } from "../api/client";
import type { MetricStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { CAN_RUN_DETECTION } from "../auth/types";
import KpiCard from "../components/KpiCard";
import KpiCardSkeleton from "../components/KpiCardSkeleton";
import StatSummary from "../components/StatSummary";
import "./Dashboard.css";

function KpiCardConnected({ metric, canRun }: { metric: MetricStatus; canRun: boolean }) {
  const { data: detail } = useMetricDetail(metric.id);
  const runDetection = useRunDetection(metric.id);

  return (
    <KpiCard
      metric={detail ?? metric}
      series={detail?.series}
      onRunDetection={() => runDetection.mutate()}
      isRunning={runDetection.isPending}
      canRun={canRun}
      lastResultStatus={runDetection.data?.status}
      lastError={runDetection.error ? (runDetection.error as Error).message : undefined}
    />
  );
}

export default function Dashboard() {
  const { data: metrics, isLoading, error } = useMetrics();
  const { user } = useAuth();
  const canRun = !!user && CAN_RUN_DETECTION.includes(user.role);

  return (
    <div className="dashboard">
      <div className="page-head">
        <div className="kicker">
          <LayoutGrid size={11} strokeWidth={2.5} style={{ marginRight: 5, verticalAlign: -1 }} aria-hidden="true" />
          Monitored KPIs
        </div>
        <h1>Dashboard</h1>
        <p className="page-sub">
          Every KPI below runs the same four-stage pipeline: noise filtering, segmentation, evidence mining, and a
          convergence check — before anything becomes a report.
        </p>
      </div>

      {error && <div className="state-msg state-error">Could not reach the API: {(error as Error).message}</div>}

      {isLoading && (
        <div className="kpi-grid">
          {Array.from({ length: 4 }).map((_, i) => (
            <KpiCardSkeleton key={i} />
          ))}
        </div>
      )}

      {!isLoading && metrics && metrics.length > 0 && <StatSummary metrics={metrics} />}

      {!isLoading && metrics?.length === 0 && (
        <div className="empty-dashboard">
          <Database size={26} strokeWidth={1.5} aria-hidden="true" />
          <h3>No metrics yet</h3>
          <p>
            {user?.role === "admin"
              ? "Create your first metric and upload its data to see the pipeline in action."
              : "Ask an admin to create one and upload data via the Data page."}
          </p>
          {user?.role === "admin" && (
            <Link to="/data" className="btn-run btn-run-lg">
              Go to Data
            </Link>
          )}
        </div>
      )}

      {!isLoading && metrics && metrics.length > 0 && (
        <div className="kpi-grid">
          {metrics.map((m) => (
            <KpiCardConnected key={m.id} metric={m} canRun={canRun} />
          ))}
        </div>
      )}
    </div>
  );
}
