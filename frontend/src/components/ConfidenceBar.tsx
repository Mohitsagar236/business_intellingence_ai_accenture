import "./ConfidenceBar.css";

export default function ConfidenceBar({ value, tone = "accent" }: { value: number; tone?: "accent" | "warn" }) {
  const pct = Math.round(value * 100);
  return (
    <div className="confidence-bar">
      <div className="confidence-track">
        <div className={`confidence-fill tone-${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="confidence-value mono">{pct}%</span>
    </div>
  );
}
