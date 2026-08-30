import { useState } from "react";
import { AlertTriangle, BookOpen, CheckCircle2, DatabaseZap, ScrollText, ShieldAlert, XCircle } from "lucide-react";
import { useAuditLog, usePlaybooks, useSuppressedLog } from "../api/client";
import type { AuditLogFilter } from "../api/types";
import "./Admin.css";

const AUDIT_ACTIONS = ["login_success", "login_failed", "authorization_denied", "metric_created", "metric_deleted"];

export default function Admin() {
  const { data: log, isLoading: logLoading } = useSuppressedLog();
  const { data: playbooks, isLoading: playbooksLoading } = usePlaybooks();

  const [auditFilter, setAuditFilter] = useState<AuditLogFilter>({});
  const { data: auditLog, isLoading: auditLoading } = useAuditLog(auditFilter);

  function updateFilter(patch: Partial<AuditLogFilter>) {
    setAuditFilter((prev) => {
      const next = { ...prev, ...patch };
      // Drop empty-string keys entirely rather than sending "user=" etc.
      for (const key of Object.keys(next) as (keyof AuditLogFilter)[]) {
        if (!next[key]) delete next[key];
      }
      return next;
    });
  }

  return (
    <div className="admin-page">
      <div className="page-head">
        <div className="kicker">Trust &amp; audit</div>
        <h1>Admin</h1>
        <p className="page-sub">
          Everything Stage 2 filtered out — logged silently rather than reported — plus the vetted playbook library
          Stage 4 matches validated causes against.
        </p>
      </div>

      <section className="admin-section">
        <h2>
          <ShieldAlert size={16} strokeWidth={2.25} aria-hidden="true" />
          Suppressed log
        </h2>
        {logLoading && <div className="state-msg">Loading…</div>}
        {!logLoading && log?.length === 0 && <div className="state-msg">Nothing suppressed yet.</div>}
        {!logLoading && log && log.length > 0 && (
          <div className="table-wrap card">
            <table>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Window</th>
                  <th>Reason</th>
                  <th>Detail</th>
                  <th>z-score</th>
                </tr>
              </thead>
              <tbody>
                {log.map((l) => (
                  <tr key={l.id}>
                    <td>{l.metric_name}</td>
                    <td className="mono">
                      {l.window_start} → {l.window_end}
                    </td>
                    <td>
                      <span className={`reason-badge reason-${l.reason}`}>
                        {l.reason === "data_quality" ? <DatabaseZap size={11} strokeWidth={2.25} aria-hidden="true" /> : <AlertTriangle size={11} strokeWidth={2.25} aria-hidden="true" />}
                        {l.reason === "data_quality" ? "Data quality" : "Not significant"}
                      </span>
                    </td>
                    <td className="detail-cell">{l.detail}</td>
                    <td className="mono">{l.z_score !== null ? l.z_score.toFixed(2) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="admin-section">
        <h2>
          <BookOpen size={16} strokeWidth={2.25} aria-hidden="true" />
          Playbook library
        </h2>
        {playbooksLoading && <div className="state-msg">Loading…</div>}
        <div className="playbook-grid">
          {playbooks?.map((p) => (
            <div className="card playbook-card" key={p.id}>
              <div className="playbook-head">
                <span className="playbook-category mono">{p.cause_category}</span>
                <span className="playbook-owner">{p.owner_department}</span>
              </div>
              <h3>{p.title}</h3>
              <ol>
                {p.actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      </section>

      <section className="admin-section">
        <h2>
          <ScrollText size={16} strokeWidth={2.25} aria-hidden="true" />
          Audit log
        </h2>
        <p className="page-sub" style={{ marginBottom: 14 }}>
          Security/accountability trail — logins, authorization denials, and metric create/delete. Admin-only, enforced server-side.
        </p>

        <div className="audit-filters">
          <label>
            User
            <input
              type="text"
              placeholder="username"
              value={auditFilter.user ?? ""}
              onChange={(e) => updateFilter({ user: e.target.value })}
            />
          </label>
          <label>
            Action
            <select value={auditFilter.action ?? ""} onChange={(e) => updateFilter({ action: e.target.value })}>
              <option value="">All actions</option>
              {AUDIT_ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </label>
          <label>
            From
            <input type="date" value={auditFilter.date_from ?? ""} onChange={(e) => updateFilter({ date_from: e.target.value })} />
          </label>
          <label>
            To
            <input type="date" value={auditFilter.date_to ?? ""} onChange={(e) => updateFilter({ date_to: e.target.value })} />
          </label>
          {Object.keys(auditFilter).length > 0 && (
            <button className="btn-secondary" onClick={() => setAuditFilter({})}>
              Clear filters
            </button>
          )}
        </div>

        {auditLoading && <div className="state-msg">Loading…</div>}
        {!auditLoading && auditLog?.length === 0 && <div className="state-msg">No audit entries match this filter.</div>}
        {!auditLoading && auditLog && auditLog.length > 0 && (
          <div className="table-wrap card">
            <table>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>User</th>
                  <th>Role</th>
                  <th>Action</th>
                  <th>Resource</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {auditLog.map((a) => (
                  <tr key={a.id}>
                    <td className="mono">{new Date(a.created_at).toLocaleString()}</td>
                    <td>{a.username ?? "—"}</td>
                    <td className="mono">{a.role ?? "—"}</td>
                    <td className="mono">{a.action}</td>
                    <td className="detail-cell">
                      {a.resource_type && <span>{a.resource_type}{a.resource_id ? ` #${a.resource_id}` : ""}</span>}
                      {a.detail && <span className="audit-detail-note">{a.resource_type ? " — " : ""}{a.detail}</span>}
                      {!a.resource_type && !a.detail && "—"}
                    </td>
                    <td>
                      {a.success ? (
                        <span className="audit-result audit-result-ok">
                          <CheckCircle2 size={12} strokeWidth={2.25} aria-hidden="true" />
                          OK
                        </span>
                      ) : (
                        <span className="audit-result audit-result-fail">
                          <XCircle size={12} strokeWidth={2.25} aria-hidden="true" />
                          Denied
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
