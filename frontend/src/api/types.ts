export type AnomalyStatus = "validated" | "ambiguous" | "suppressed_noise" | "suppressed_data_quality" | "unknown";
export type RunDetectionStatus = AnomalyStatus | "no_data";

export interface MetricStatus {
  id: number;
  key: string;
  name: string;
  department: string;
  unit: string;
  aggregation: "sum" | "mean";
  dimensions: string[];
  seasonality_period: number;
  latest_status: AnomalyStatus | null;
  latest_anomaly_id: number | null;
  latest_checked_at: string | null;
}

export interface MetricCreate {
  key: string;
  name: string;
  department: string;
  unit: string;
  aggregation: "sum" | "mean";
  seasonality_period: number;
  dimensions: string[];
}

export interface UploadResult {
  rows_inserted: number;
  date_range_start: string | null;
  date_range_end: string | null;
  warnings: string[];
  duplicates_skipped: number;
}

export interface SeriesPoint {
  date: string;
  value: number;
  trend: number;
  seasonal: number;
  resid: number;
  ci_upper: number;
  ci_lower: number;
}

export interface AnomalySummary {
  id: number;
  metric_id: number;
  window_start: string;
  window_end: string;
  magnitude_pct: number;
  significance_score: number;
  status: AnomalyStatus;
  created_at: string;
}

export interface MetricDetail extends MetricStatus {
  series: SeriesPoint[];
  anomalies: AnomalySummary[];
  insufficient_history: boolean;
  observation_count: number;
}

export interface Segment {
  dimension: string;
  value: string;
  contribution_score: number;
  is_primary: boolean;
}

export interface Evidence {
  id: number;
  type: "structured" | "unstructured";
  source: string;
  description: string;
  correlation: number | null;
  lag_days: number | null;
  theme_keywords: string[] | null;
  spike_ratio: number | null;
  excerpts: string[];
  window_start: string | null;
  window_end: string | null;
}

export interface Hypothesis {
  id: number;
  cause_category: string;
  cause_display: string;
  confidence: number;
  rank: number;
  status: "validated" | "candidate";
  disambiguation_gap: string | null;
  structured_evidence_id: number | null;
  unstructured_evidence_id: number | null;
}

export interface Report {
  id: number;
  status: string;
  problem_statement: string;
  cause_statement: string;
  confidence_statement: string;
  action_statement: string;
  citations: number[];
  stripped_claims: string[];
  routed_to: string;
  generated_by: "claude" | "gemini" | "template";
  created_at: string;
}

export interface AnomalyDetail extends AnomalySummary {
  metric: { id: number; key: string; name: string; department: string; unit: string; aggregation: string };
  segments: Segment[];
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  report: Report | null;
}

export interface ReportListItem {
  id: number;
  anomaly_id: number;
  status: string;
  routed_to: string;
  created_at: string;
  metric_name: string;
  problem_statement: string;
}

export interface SuppressedLogEntry {
  id: number;
  metric_id: number;
  metric_name: string;
  window_start: string;
  window_end: string;
  reason: "not_significant" | "data_quality";
  detail: string;
  z_score: number | null;
  created_at: string;
}

export interface AuditLogEntry {
  id: number;
  created_at: string;
  username: string | null;
  role: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  success: boolean;
  detail: string | null;
}

export interface AuditLogFilter {
  user?: string;
  action?: string;
  date_from?: string;
  date_to?: string;
}

export interface Playbook {
  id: number;
  cause_category: string;
  title: string;
  owner_department: string;
  actions: string[];
  version: number;
}

export interface RunDetectionResult {
  status: RunDetectionStatus;
  anomaly_id: number | null;
  report_id: number | null;
  suppressed_log_id: number | null;
  detail: string | null;
  z_score: number | null;
}

export const DETECTION_STAGES = [
  "data_quality",
  "baseline_analysis",
  "anomaly_detection",
  "segmentation",
  "structured_evidence",
  "nlp_evidence",
  "convergence",
  "recommendation",
] as const;

export type DetectionStageName = (typeof DETECTION_STAGES)[number];

export const DETECTION_STAGE_LABELS: Record<DetectionStageName, string> = {
  data_quality: "Data Quality",
  baseline_analysis: "Baseline Analysis",
  anomaly_detection: "Anomaly Detection",
  segmentation: "Segmentation",
  structured_evidence: "Structured Evidence",
  nlp_evidence: "NLP Evidence",
  convergence: "Convergence",
  recommendation: "Recommendation",
};

export interface DetectionStage {
  stage: DetectionStageName;
  ok: boolean;
  detail: string | null;
}

export interface DetectionJob {
  job_id: string;
  status: "running" | "done" | "failed";
  stages: DetectionStage[];
  result: RunDetectionResult | null;
  error: string | null;
}
