import "./StatusPill.css";

export const STATUS_LABELS: Record<string, string> = {
  validated: "Validated",
  ambiguous: "Ambiguous",
  suppressed_noise: "Normal variation",
  suppressed_data_quality: "Data quality issue",
  unknown: "Not yet checked",
  candidate: "Candidate",
  no_data: "No data uploaded",
};

const CLASS: Record<string, string> = {
  validated: "pill-ok",
  ambiguous: "pill-warn",
  suppressed_noise: "pill-mute",
  suppressed_data_quality: "pill-crit",
  unknown: "pill-mute",
  candidate: "pill-warn",
  no_data: "pill-mute",
};

export default function StatusPill({ status }: { status: string | null | undefined }) {
  const key = status ?? "unknown";
  return <span className={`status-pill ${CLASS[key] ?? "pill-mute"}`}>{STATUS_LABELS[key] ?? key}</span>;
}
