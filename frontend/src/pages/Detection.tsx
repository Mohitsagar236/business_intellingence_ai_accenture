import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, CircleDashed, Loader2, Play, X } from "lucide-react";
import { useDetectionJob, useMetricDetail, useMetrics, useStartDetectionJob } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { DETECTION_STAGES, DETECTION_STAGE_LABELS, type DetectionStageName } from "../api/types";
import StatusPill, { STATUS_LABELS } from "../components/StatusPill";
import "./Detection.css";

type StageState = "done_ok" | "done_failed" | "running" | "waiting";

export default function Detection() {
  const { user } = useAuth();
  const { data: metrics, isLoading: metricsLoading } = useMetrics();
  const [metricId, setMetricId] = useState<number | undefined>(undefined);
  const [jobId, setJobId] = useState<string | undefined>(undefined);
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");

  const startJob = useStartDetectionJob(metricId);
  const { data: job } = useDetectionJob(jobId);
  const { data: metricDetail } = useMetricDetail(metricId);

  const selectedMetric = metrics?.find((m) => m.id === metricId);
  const isRunning = job?.status === "running" || startJob.isPending;

  const availableStart = metricDetail?.series[0]?.date;
  const availableEnd = metricDetail?.series[metricDetail.series.length - 1]?.date;
  const hasCustomWindow = windowStart !== "" || windowEnd !== "";
  const customWindowIncomplete = hasCustomWindow && (windowStart === "" || windowEnd === "");
  const customWindowInverted = windowStart !== "" && windowEnd !== "" && windowStart > windowEnd;
  const windowError = customWindowIncomplete
    ? "Pick both a start and end date, or clear both to use the most recent window."
    : customWindowInverted
      ? "Start date must be on or before the end date."
      : undefined;

  function handleStart() {
    if (!metricId || windowError) return;
    startJob.mutate(
      hasCustomWindow ? { windowStart, windowEnd } : {},
      { onSuccess: (data) => setJobId(data.job_id) },
    );
  }

  function handleReset() {
    setJobId(undefined);
    startJob.reset();
  }

  function handleMetricChange(next: number | undefined) {
    setMetricId(next);
    setWindowStart("");
    setWindowEnd("");
  }

  // A stage counts as reached only once the backend has actually reported an event for it —
  // never inferred from elapsed time. The first stage with no event yet is "running" only
  // while the job itself is still going; everything after that is "waiting".
  function stageState(stage: DetectionStageName, index: number): StageState {
    const event = job?.stages.find((s) => s.stage === stage);
    if (event) return event.ok ? "done_ok" : "done_failed";
    if (!job || job.status !== "running") return "waiting";
    const firstUnreached = DETECTION_STAGES.findIndex((s) => !job.stages.some((e) => e.stage === s));
    return index === firstUnreached ? "running" : "waiting";
  }

  return (
    <div className="detection-page">
      <div className="page-head">
        <div className="kicker">Stage 2 → 4</div>
        <h1>Run Detection</h1>
        <p className="page-sub">
          Pick a KPI and run the noise-filtering → root-cause → recommendation pipeline against a window of its history. Each
          step below only turns green once that real backend stage has actually finished — nothing here is simulated.
        </p>
      </div>

      <div className="card detection-setup">
        <label className="detection-field">
          <span>KPI</span>
          <select
            value={metricId ?? ""}
            disabled={isRunning || metricsLoading}
            onChange={(e) => handleMetricChange(e.target.value ? Number(e.target.value) : undefined)}
          >
            <option value="">Select a metric…</option>
            {metrics?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} — {m.department}
              </option>
            ))}
          </select>
        </label>

        {selectedMetric && (
          <>
            <div className="detection-meta">
              <StatusPill status={selectedMetric.latest_status} />
              <span className="detection-window-note mono">
                {hasCustomWindow ? "Runs against the custom window below." : "Leave dates blank to run on the most recent window."}
              </span>
            </div>

            <div className="detection-field">
              <span>Report window (optional)</span>
              <div className="detection-window-row">
                <input
                  type="date"
                  value={windowStart}
                  min={availableStart}
                  max={availableEnd}
                  disabled={isRunning}
                  onChange={(e) => setWindowStart(e.target.value)}
                />
                <span className="detection-window-sep">→</span>
                <input
                  type="date"
                  value={windowEnd}
                  min={availableStart}
                  max={availableEnd}
                  disabled={isRunning}
                  onChange={(e) => setWindowEnd(e.target.value)}
                />
                {hasCustomWindow && (
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={isRunning}
                    onClick={() => {
                      setWindowStart("");
                      setWindowEnd("");
                    }}
                  >
                    Clear
                  </button>
                )}
              </div>
              {availableStart && availableEnd && (
                <span className="detection-window-note mono">
                  Data available from {availableStart} to {availableEnd}.
                </span>
              )}
              {windowError && <span className="detection-window-note detection-window-error">{windowError}</span>}
            </div>
          </>
        )}

        <div className="detection-actions">
          {!job || job.status !== "running" ? (
            <button className="btn-run btn-run-lg" onClick={handleStart} disabled={!metricId || isRunning || !!windowError}>
              <Play size={13} strokeWidth={2.25} aria-hidden="true" />
              {isRunning ? "Starting…" : "Start Detection"}
            </button>
          ) : (
            <button className="btn-run btn-run-lg" disabled>
              <Loader2 size={13} strokeWidth={2.25} className="spin" aria-hidden="true" />
              Running…
            </button>
          )}
          {job && job.status !== "running" && (
            <button className="btn-secondary" onClick={handleReset}>
              Run another
            </button>
          )}
        </div>

        {startJob.isError && <div className="run-feedback run-feedback-error">{(startJob.error as Error).message}</div>}
      </div>

      {(job || isRunning) && (
        <div className="card stage-checklist">
          {DETECTION_STAGES.map((stage, i) => {
            const state = stageState(stage, i);
            const event = job?.stages.find((s) => s.stage === stage);
            return (
              <div key={stage} className={`stage-row stage-${state}`}>
                <span className="stage-icon" aria-hidden="true">
                  {state === "done_ok" && <Check size={14} strokeWidth={3} />}
                  {state === "done_failed" && <X size={14} strokeWidth={3} />}
                  {state === "running" && <Loader2 size={14} strokeWidth={2.5} className="spin" />}
                  {state === "waiting" && <CircleDashed size={14} strokeWidth={2} />}
                </span>
                <span className="stage-label">{DETECTION_STAGE_LABELS[stage]}</span>
                {event?.detail && <span className="stage-detail">{event.detail}</span>}
              </div>
            );
          })}
        </div>
      )}

      {job?.status === "failed" && <div className="state-error" style={{ marginTop: 16 }}>Detection failed: {job.error}</div>}

      {job?.status === "done" && job.result && (
        <div className="card detection-result">
          <div className="detection-result-head">
            <StatusPill status={job.result.status} />
            <span>{STATUS_LABELS[job.result.status] ?? job.result.status}</span>
          </div>

          {(job.result.status === "validated" || job.result.status === "ambiguous") && job.result.anomaly_id && (
            <Link className="btn-run" to={`/anomalies/${job.result.anomaly_id}`}>
              View report
            </Link>
          )}

          {(job.result.status === "suppressed_noise" || job.result.status === "suppressed_data_quality") && (
            <>
              <p className="detection-result-note">
                No business report was generated — this deviation was {job.result.status === "suppressed_noise" ? "normal variation" : "a data-quality issue"},
                logged silently for audit rather than surfaced as a finding.
              </p>
              {user?.role === "admin" && (
                <Link className="btn-secondary" to="/admin">
                  View suppressed log
                </Link>
              )}
            </>
          )}

          {job.result.status === "no_data" && (
            <p className="detection-result-note">{job.result.detail ?? "No observations have been uploaded for this metric yet."}</p>
          )}
        </div>
      )}
    </div>
  );
}
