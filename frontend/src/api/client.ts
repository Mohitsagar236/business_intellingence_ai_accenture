import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getToken, setToken } from "../auth/tokenStore";
import type {
  AnomalyDetail,
  AnomalySummary,
  AuditLogEntry,
  AuditLogFilter,
  DetectionJob,
  MetricCreate,
  MetricDetail,
  MetricStatus,
  Playbook,
  ReportListItem,
  Report,
  RunDetectionResult,
  SuppressedLogEntry,
  UploadResult,
} from "./types";

const BASE = "/api";

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    // Session expired or was never valid — clear it and force a full reload so the
    // AuthProvider re-checks on mount and the router lands on /login.
    setToken(null);
    if (!location.pathname.startsWith("/login")) location.href = "/login";
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) {
    return undefined as T; // No Content — e.g. DELETE — has no body to parse.
  }
  return res.json() as Promise<T>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...init,
  });
  return handleResponse<T>(res);
}

/** For file uploads — must NOT set Content-Type ourselves, the browser adds the multipart
 * boundary automatically when the body is a FormData instance. */
async function requestForm<T>(path: string, formData: FormData): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  return handleResponse<T>(res);
}

export function useMetrics() {
  return useQuery({
    queryKey: ["metrics"],
    queryFn: () => request<MetricStatus[]>("/metrics"),
    refetchInterval: false,
  });
}

export function useMetricDetail(metricId: number | undefined) {
  return useQuery({
    queryKey: ["metric", metricId],
    queryFn: () => request<MetricDetail>(`/metrics/${metricId}`),
    enabled: metricId !== undefined,
  });
}

/** Optional custom window — both bounds must be given together or omitted, matching the
 * backend's rule (app/api/metrics.py::_resolve_window). Omitting them keeps the pipeline's own
 * "most recent window" default. */
export interface DetectionWindow {
  windowStart?: string;
  windowEnd?: string;
}

function windowQuery({ windowStart, windowEnd }: DetectionWindow = {}): string {
  if (!windowStart || !windowEnd) return "";
  const params = new URLSearchParams({ window_start: windowStart, window_end: windowEnd });
  return `?${params.toString()}`;
}

export function useRunDetection(metricId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (window: DetectionWindow = {}) =>
      request<RunDetectionResult>(`/metrics/${metricId}/run-detection${windowQuery(window)}`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      queryClient.invalidateQueries({ queryKey: ["metric", metricId] });
      queryClient.invalidateQueries({ queryKey: ["anomalies"] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["suppressed-log"] });
    },
  });
}

export function useStartDetectionJob(metricId: number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (window: DetectionWindow = {}) =>
      request<DetectionJob>(`/metrics/${metricId}/detections${windowQuery(window)}`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      queryClient.invalidateQueries({ queryKey: ["metric", metricId] });
      queryClient.invalidateQueries({ queryKey: ["anomalies"] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["suppressed-log"] });
    },
  });
}

/** Polls a running detection job for real stage progress. Stops polling the instant the
 * backend reports "done" or "failed" — never fabricates progress between polls. */
export function useDetectionJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ["detection-job", jobId],
    queryFn: () => request<DetectionJob>(`/metrics/detections/${jobId}`),
    enabled: jobId !== undefined,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 400 : false),
  });
}

export function useAnomalies(status?: string) {
  return useQuery({
    queryKey: ["anomalies", status ?? "all"],
    queryFn: () => request<AnomalySummary[]>(`/anomalies${status ? `?status=${status}` : ""}`),
  });
}

export function useAnomalyDetail(anomalyId: number | undefined) {
  return useQuery({
    queryKey: ["anomaly", anomalyId],
    queryFn: () => request<AnomalyDetail>(`/anomalies/${anomalyId}`),
    enabled: anomalyId !== undefined,
  });
}

export function useReports(department?: string) {
  return useQuery({
    queryKey: ["reports", department ?? "all"],
    queryFn: () => request<ReportListItem[]>(`/reports${department ? `?department=${department}` : ""}`),
  });
}

export function useReport(reportId: number | undefined) {
  return useQuery({
    queryKey: ["report", reportId],
    queryFn: () => request<Report>(`/reports/${reportId}`),
    enabled: reportId !== undefined,
  });
}

export function useSuppressedLog() {
  return useQuery({
    queryKey: ["suppressed-log"],
    queryFn: () => request<SuppressedLogEntry[]>("/admin/suppressed-log"),
  });
}

export function usePlaybooks() {
  return useQuery({
    queryKey: ["playbooks"],
    queryFn: () => request<Playbook[]>("/admin/playbooks"),
  });
}

export function useAuditLog(filter: AuditLogFilter) {
  const params = new URLSearchParams();
  if (filter.user) params.set("user", filter.user);
  if (filter.action) params.set("action", filter.action);
  if (filter.date_from) params.set("date_from", filter.date_from);
  if (filter.date_to) params.set("date_to", filter.date_to);
  const qs = params.toString();
  return useQuery({
    queryKey: ["audit-log", filter],
    queryFn: () => request<AuditLogEntry[]>(`/admin/audit-log${qs ? `?${qs}` : ""}`),
  });
}

export function useCreateMetric() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: MetricCreate) => request<MetricStatus>("/metrics", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["metrics"] }),
  });
}

export function useDeleteMetric() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (metricId: number) => request<void>(`/metrics/${metricId}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["metrics"] }),
  });
}

export function useUploadObservations(metricId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return requestForm<UploadResult>(`/metrics/${metricId}/observations/upload`, form);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["metrics"] });
      queryClient.invalidateQueries({ queryKey: ["metric", metricId] });
    },
  });
}

export function useUploadTextEvidence() {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return requestForm<UploadResult>("/text-evidence/upload", form);
    },
  });
}

/** Template endpoints require the same admin auth as everything else, so a plain <a href>
 * won't carry the token — fetch as a blob and trigger the save ourselves. */
async function downloadFile(path: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`${res.status}: could not download ${filename}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function downloadObservationsTemplate(metricId: number, metricKey: string): Promise<void> {
  return downloadFile(`/metrics/${metricId}/observations/template`, `${metricKey}_observations_template.csv`);
}

export function downloadTextEvidenceTemplate(): Promise<void> {
  return downloadFile("/text-evidence/template", "text_evidence_template.csv");
}
