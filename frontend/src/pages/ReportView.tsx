import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ClipboardList, Compass, Gauge, HelpCircle, LayoutGrid, ScrollText, ShieldAlert, Sparkles, Wrench } from "lucide-react";
import { useAnomalyDetail, useMetricDetail } from "../api/client";
import StatusPill from "../components/StatusPill";
import CitedText from "../components/CitedText";
import EvidencePanel from "../components/EvidencePanel";
import EvidenceTimeline from "../components/EvidenceTimeline";
import HypothesisCard from "../components/HypothesisCard";
import RootCauseChain from "../components/RootCauseChain";
import SegmentContributionChart from "../components/SegmentContributionChart";
import TimeSeriesChart from "../components/TimeSeriesChart";
import "./ReportView.css";

export default function ReportView() {
  const { anomalyId } = useParams();
  const { data: anomaly, isLoading, isError, error } = useAnomalyDetail(Number(anomalyId));
  const { data: metric } = useMetricDetail(anomaly?.metric.id);

  if (isError) {
    const isForbidden = error instanceof Error && error.message.startsWith("403");
    return (
      <div className="report-view">
        <Link to="/reports" className="back-link">
          <ArrowLeft size={13} strokeWidth={2.25} aria-hidden="true" />
          Reports
        </Link>
        <div className="state-error" style={{ marginTop: 16 }}>
          {isForbidden
            ? "This report belongs to a different department and isn't visible from your account."
            : "This anomaly couldn't be loaded."}
        </div>
      </div>
    );
  }

  if (isLoading || !anomaly) {
    return (
      <div className="report-view">
        <div className="skeleton" style={{ width: 140, height: 16, marginBottom: 22, borderRadius: 6 }} />
        <div className="card report-card">
          <div className="skeleton" style={{ height: 220, borderRadius: 8 }} />
        </div>
      </div>
    );
  }

  const report = anomaly.report;
  const primarySegments = anomaly.segments.filter((s) => s.is_primary);
  const isValidated = anomaly.status === "validated";
  const hasGaps = !isValidated && anomaly.hypotheses.some((h) => h.disambiguation_gap);

  return (
    <div className="report-view">
      <Link to={`/metrics/${anomaly.metric.id}`} className="back-link">
        <ArrowLeft size={13} strokeWidth={2.25} aria-hidden="true" />
        {anomaly.metric.name}
      </Link>

      <div className="page-head">
        <div className="kicker">{anomaly.metric.department}</div>
        <div className="report-title-row">
          <h1>
            {anomaly.window_start} → {anomaly.window_end}
          </h1>
          <StatusPill status={anomaly.status} />
        </div>
      </div>

      {metric && metric.series.length > 0 && (
        <div className="card" style={{ padding: "20px 22px", marginBottom: 28 }}>
          <h2 className="section-heading">Trend &amp; Anomaly Window</h2>
          <TimeSeriesChart series={metric.series} highlightStart={anomaly.window_start} highlightEnd={anomaly.window_end} />
        </div>
      )}

      {!report && <div className="state-msg">This anomaly has no report yet.</div>}

      {report && (
        <>
          <div className="card report-card" style={{ marginBottom: 28 }}>
            <section className="report-section">
              <span className="report-label">
                <ScrollText size={13} strokeWidth={2.25} aria-hidden="true" />
                Problem
              </span>
              <p className="problem-text">{report.problem_statement}</p>
            </section>
          </div>

          <div className="card" style={{ padding: "22px 24px", marginBottom: 28 }}>
            <h2 className="section-heading">
              <LayoutGrid size={14} strokeWidth={2.25} aria-hidden="true" style={{ marginRight: 6, verticalAlign: -2 }} />
              Affected Segment
            </h2>
            {primarySegments.length > 0 ? (
              <div className="segment-tags" style={{ marginBottom: 16 }}>
                {primarySegments.map((s) => (
                  <span key={`${s.dimension}-${s.value}`} className="segment-tag mono">
                    {s.dimension}={s.value}
                  </span>
                ))}
              </div>
            ) : (
              <p className="section-note" style={{ marginBottom: 16 }}>
                No dominant segment was isolated — the deviation is spread across segments rather than concentrated in one.
              </p>
            )}
            <SegmentContributionChart segments={anomaly.segments} />
          </div>

          <div className="card root-cause-chain-card">
            <h2 className="section-heading">Root Cause Evidence Chain</h2>
            <RootCauseChain anomaly={anomaly} />
          </div>

          <EvidencePanel evidence={anomaly.evidence} />

          {anomaly.evidence.length > 0 && (
            <div className="card" style={{ padding: "22px 24px", marginBottom: 28 }}>
              <h2 className="section-heading">Evidence Timeline</h2>
              <EvidenceTimeline anomaly={anomaly} />
            </div>
          )}

          <div className="card report-card" style={{ marginBottom: 28 }}>
            <section className="report-section">
              <span className="report-label">
                <Compass size={13} strokeWidth={2.25} aria-hidden="true" />
                Cause
              </span>
              <CitedText text={report.cause_statement} />
            </section>

            <section className="report-section">
              <span className="report-label">
                <Gauge size={13} strokeWidth={2.25} aria-hidden="true" />
                Confidence
              </span>
              <CitedText text={report.confidence_statement} />
            </section>
          </div>

          {hasGaps && (
            <div className="hypotheses-section">
              <h2>
                <HelpCircle size={15} strokeWidth={2.25} aria-hidden="true" style={{ marginRight: 6, verticalAlign: -2 }} />
                Evidence Gap
              </h2>
              <div className="hypotheses-grid">
                {anomaly.hypotheses.map((h) => (
                  <HypothesisCard key={h.id} hypothesis={h} />
                ))}
              </div>
            </div>
          )}

          <div className="card report-card">
            <section className="report-section">
              <span className="report-label">
                {isValidated ? <Wrench size={13} strokeWidth={2.25} aria-hidden="true" /> : <ClipboardList size={13} strokeWidth={2.25} aria-hidden="true" />}
                Recommendation
              </span>
              <p className="action-text">{report.action_statement}</p>
            </section>

            <footer className="report-footer">
              <span>
                Routed to <strong>{report.routed_to}</strong>
              </span>
              <span className="mono generated-by">
                <Sparkles size={11} strokeWidth={2.25} aria-hidden="true" />
                generated by: {report.generated_by}
              </span>
              {report.stripped_claims.length > 0 && (
                <span className="stripped-note" title={report.stripped_claims.join(" / ")}>
                  <ShieldAlert size={12} strokeWidth={2.25} aria-hidden="true" />
                  {report.stripped_claims.length} ungrounded sentence{report.stripped_claims.length > 1 ? "s" : ""} removed
                </span>
              )}
            </footer>
          </div>
        </>
      )}
    </div>
  );
}
