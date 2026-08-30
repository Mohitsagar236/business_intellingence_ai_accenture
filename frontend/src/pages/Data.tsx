import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { Database, Download, MessageSquareText, PlusCircle, Trash2, UploadCloud } from "lucide-react";
import {
  downloadObservationsTemplate,
  downloadTextEvidenceTemplate,
  useCreateMetric,
  useDeleteMetric,
  useMetricDetail,
  useMetrics,
  useUploadObservations,
  useUploadTextEvidence,
} from "../api/client";
import type { MetricStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { departmentIcon } from "../components/departmentIcon";
import "./Data.css";

function CreateMetricForm() {
  const createMetric = useCreateMetric();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [unit, setUnit] = useState("");
  const [aggregation, setAggregation] = useState<"sum" | "mean">("sum");
  const [seasonalityPeriod, setSeasonalityPeriod] = useState(7);
  const [dimensionsText, setDimensionsText] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const dimensions = dimensionsText
      .split(",")
      .map((d) => d.trim())
      .filter(Boolean);
    createMetric.mutate(
      { key, name, department, unit, aggregation, seasonality_period: seasonalityPeriod, dimensions },
      {
        onSuccess: () => {
          setKey("");
          setName("");
          setDepartment("");
          setUnit("");
          setDimensionsText("");
        },
      }
    );
  }

  return (
    <form className="card create-metric-form" onSubmit={handleSubmit}>
      <h3>
        <PlusCircle size={16} strokeWidth={2.25} aria-hidden="true" />
        Create a metric
      </h3>
      <div className="form-grid">
        <label>
          Key <span className="field-hint">(unique, no spaces)</span>
          <input value={key} onChange={(e) => setKey(e.target.value)} required placeholder="revenue" />
        </label>
        <label>
          Display name
          <input value={name} onChange={(e) => setName(e.target.value)} required placeholder="Revenue" />
        </label>
        <label>
          Department
          <input value={department} onChange={(e) => setDepartment(e.target.value)} required placeholder="Sales" />
        </label>
        <label>
          Unit
          <input value={unit} onChange={(e) => setUnit(e.target.value)} required placeholder="USD" />
        </label>
        <label>
          Aggregation across segments
          <select value={aggregation} onChange={(e) => setAggregation(e.target.value as "sum" | "mean")}>
            <option value="sum">sum</option>
            <option value="mean">mean</option>
          </select>
        </label>
        <label>
          Seasonality period <span className="field-hint">(7 = weekly)</span>
          <input
            type="number"
            min={2}
            value={seasonalityPeriod}
            onChange={(e) => setSeasonalityPeriod(Number(e.target.value))}
          />
        </label>
        <label className="span-2">
          Dimensions <span className="field-hint">(comma-separated, e.g. "region, product")</span>
          <input value={dimensionsText} onChange={(e) => setDimensionsText(e.target.value)} placeholder="region, product" />
        </label>
      </div>
      <button type="submit" className="btn-run" style={{ alignSelf: "flex-start" }} disabled={createMetric.isPending}>
        {createMetric.isPending ? "Creating…" : "Create metric"}
      </button>
      {createMetric.isError && <div className="run-feedback run-feedback-error">{(createMetric.error as Error).message}</div>}
      {createMetric.isSuccess && <div className="run-feedback run-feedback-ok">Created "{createMetric.data.name}".</div>}
    </form>
  );
}

function MetricRow({ metric, canManage }: { metric: MetricStatus; canManage: boolean }) {
  const { data: detail } = useMetricDetail(metric.id);
  const uploadObs = useUploadObservations(metric.id);
  const deleteMetric = useDeleteMetric();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const DeptIcon = departmentIcon(metric.department);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadObs.mutate(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleDelete() {
    if (confirm(`Delete "${metric.name}" and all of its data? This cannot be undone.`)) {
      deleteMetric.mutate(metric.id);
    }
  }

  return (
    <div className="card metric-row">
      <div className="metric-row-head">
        <div>
          <div className="kpi-dept">
            <DeptIcon size={12} strokeWidth={2.25} aria-hidden="true" />
            {metric.department}
          </div>
          <Link to={`/metrics/${metric.id}`} className="kpi-name">
            {metric.name}
          </Link>
        </div>
        {canManage && (
          <button className="btn-secondary btn-danger" onClick={handleDelete} disabled={deleteMetric.isPending}>
            <Trash2 size={13} strokeWidth={2.25} aria-hidden="true" />
            Delete
          </button>
        )}
      </div>

      <div className="metric-row-meta mono">
        {detail ? `${detail.observation_count} observation${detail.observation_count === 1 ? "" : "s"}` : "…"}
        {detail?.series.length ? ` · ${detail.series[0].date} → ${detail.series[detail.series.length - 1].date}` : ""}
        {metric.dimensions.length > 0 && ` · dims: ${metric.dimensions.join(", ")}`}
      </div>

      <div className="metric-row-actions">
        <button className="btn-secondary" onClick={() => downloadObservationsTemplate(metric.id, metric.key)}>
          <Download size={13} strokeWidth={2.25} aria-hidden="true" />
          Download template
        </button>
        <label className="btn-run file-btn">
          <UploadCloud size={13} strokeWidth={2.25} aria-hidden="true" />
          {uploadObs.isPending ? "Uploading…" : "Upload observations CSV/Excel"}
          <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls" onChange={handleFileChange} disabled={uploadObs.isPending} />
        </label>
      </div>

      {uploadObs.isError && <div className="run-feedback run-feedback-error">{(uploadObs.error as Error).message}</div>}
      {uploadObs.isSuccess && (
        <div className="run-feedback run-feedback-ok">
          Inserted {uploadObs.data.rows_inserted} row(s), {uploadObs.data.date_range_start} → {uploadObs.data.date_range_end}.
          {uploadObs.data.duplicates_skipped > 0 &&
            ` ${uploadObs.data.duplicates_skipped} duplicate row(s) (same date/segment already on file for this metric) were skipped.`}
        </div>
      )}
    </div>
  );
}

function TextEvidenceUploader() {
  const uploadText = useUploadTextEvidence();
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) uploadText.mutate(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  return (
    <div className="card text-evidence-card">
      <h3>
        <MessageSquareText size={16} strokeWidth={2.25} aria-hidden="true" />
        Upload unstructured evidence
      </h3>
      <p className="page-sub">
        Support tickets, call notes, survey responses — not tied to one metric. Text is PII-redacted before storage.
      </p>
      <div className="metric-row-actions">
        <button className="btn-secondary" onClick={() => downloadTextEvidenceTemplate()}>
          <Download size={13} strokeWidth={2.25} aria-hidden="true" />
          Download template
        </button>
        <label className="btn-run file-btn">
          <UploadCloud size={13} strokeWidth={2.25} aria-hidden="true" />
          {uploadText.isPending ? "Uploading…" : "Upload text CSV/Excel"}
          <input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls" onChange={handleFileChange} disabled={uploadText.isPending} />
        </label>
      </div>
      {uploadText.isError && <div className="run-feedback run-feedback-error">{(uploadText.error as Error).message}</div>}
      {uploadText.isSuccess && (
        <div className="run-feedback run-feedback-ok">
          Accepted {uploadText.data.rows_inserted} row(s), {uploadText.data.date_range_start} → {uploadText.data.date_range_end}.
          {uploadText.data.duplicates_skipped > 0 &&
            ` ${uploadText.data.duplicates_skipped} duplicate row(s) (same text/date/source/segment as an existing record) were skipped.`}
        </div>
      )}
    </div>
  );
}

export default function Data() {
  const { data: metrics, isLoading } = useMetrics();
  const { user } = useAuth();
  const canManageMetrics = user?.role === "admin";

  return (
    <div className="data-page">
      <div className="page-head">
        <div className="kicker">Ingestion</div>
        <h1>Data</h1>
        <p className="page-sub">
          {canManageMetrics
            ? "Create a metric, then upload its observations as a CSV or Excel file. Upload unstructured evidence (tickets, call notes) separately — the root-cause engine matches it to anomalies by date and segment."
            : "Upload observations for an existing metric as a CSV or Excel file, or upload unstructured evidence (tickets, call notes) separately. Creating or deleting metrics requires an admin."}
        </p>
      </div>

      {canManageMetrics && <CreateMetricForm />}

      <section className="metrics-section">
        <h2>
          <Database size={15} strokeWidth={2.25} aria-hidden="true" />
          Metrics
        </h2>
        {isLoading && <div className="state-msg">Loading…</div>}
        {metrics?.length === 0 && (
          <div className="state-msg">{canManageMetrics ? "No metrics yet — create one above." : "No metrics yet — ask an admin to create one."}</div>
        )}
        <div className="metric-list">
          {metrics?.map((m) => (
            <MetricRow key={m.id} metric={m} canManage={canManageMetrics} />
          ))}
        </div>
      </section>

      <section className="metrics-section">
        <h2>
          <MessageSquareText size={15} strokeWidth={2.25} aria-hidden="true" />
          Unstructured evidence
        </h2>
        <TextEvidenceUploader />
      </section>
    </div>
  );
}
