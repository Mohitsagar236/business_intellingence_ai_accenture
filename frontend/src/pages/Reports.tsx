import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Inbox } from "lucide-react";
import { useReports } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import StatusPill from "../components/StatusPill";
import "./Reports.css";

const DEPARTMENTS = ["Sales", "Finance", "Support", "Customer Success", "Engineering", "Data Engineering", "Operations"];

export default function Reports() {
  const { user } = useAuth();
  const isDeptHead = user?.role === "dept_head";
  // A Department Head's inbox is scoped to their own department server-side (app/api/reports.py
  // ignores any client-supplied `department` param for this role) — the switcher below is
  // hidden for them entirely rather than offered and silently ignored.
  const [department, setDepartment] = useState<string | undefined>(isDeptHead ? user.department ?? undefined : undefined);
  const { data: reports, isLoading } = useReports(department);

  return (
    <div className="reports-page">
      <div className="page-head">
        <div className="kicker">Department inboxes</div>
        <h1>Reports</h1>
        <p className="page-sub">Every diagnosis Stage 4 has routed so far, newest first — filter by the department it was sent to.</p>
      </div>

      {isDeptHead ? (
        <div className="dept-filter">
          <span className="btn-secondary active" aria-current="true">
            {user.department ?? "Unassigned"}
          </span>
          <span className="page-sub" style={{ margin: 0 }}>
            Your inbox is scoped to this department — enforced by the server, not just this filter.
          </span>
        </div>
      ) : (
        <div className="dept-filter">
          <button className={`btn-secondary ${!department ? "active" : ""}`} onClick={() => setDepartment(undefined)}>
            All
          </button>
          {DEPARTMENTS.map((d) => (
            <button key={d} className={`btn-secondary ${department === d ? "active" : ""}`} onClick={() => setDepartment(d)}>
              {d}
            </button>
          ))}
        </div>
      )}

      {isLoading && (
        <div className="report-list">
          {Array.from({ length: 3 }).map((_, i) => (
            <div className="card report-row-skeleton" key={i}>
              <div className="skeleton" style={{ width: "40%", height: 14, marginBottom: 10 }} />
              <div className="skeleton" style={{ width: "70%", height: 12 }} />
            </div>
          ))}
        </div>
      )}

      {!isLoading && reports?.length === 0 && (
        <div className="empty-block-inline">
          <Inbox size={20} strokeWidth={1.75} aria-hidden="true" />
          <span>No reports routed to this department yet.</span>
        </div>
      )}

      <div className="report-list">
        {reports?.map((r) => (
          <Link to={`/anomalies/${r.anomaly_id}`} key={r.id} className="card card-hover report-row">
            <div className="report-row-main">
              <div className="report-row-head">
                <span className="report-row-metric">{r.metric_name}</span>
                <StatusPill status={r.status} />
              </div>
              <p className="report-row-problem">{r.problem_statement}</p>
            </div>
            <div className="report-row-meta">
              <span className="mono">{r.routed_to}</span>
              <span className="mono">{new Date(r.created_at).toLocaleDateString()}</span>
            </div>
            <ChevronRight size={15} strokeWidth={2} className="report-row-chevron" aria-hidden="true" />
          </Link>
        ))}
      </div>
    </div>
  );
}
