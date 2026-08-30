import "./KpiCard.css";

export default function KpiCardSkeleton() {
  return (
    <div className="kpi-card">
      <div className="kpi-card-head">
        <div style={{ flex: 1 }}>
          <div className="skeleton" style={{ width: 70, height: 10, marginBottom: 8 }} />
          <div className="skeleton" style={{ width: "70%", height: 18 }} />
        </div>
        <div className="skeleton" style={{ width: 76, height: 20, borderRadius: 999 }} />
      </div>
      <div className="skeleton" style={{ height: 44, borderRadius: 6 }} />
      <div className="kpi-card-foot">
        <div className="skeleton" style={{ width: 60, height: 10 }} />
        <div className="skeleton" style={{ width: 96, height: 26, borderRadius: 7 }} />
      </div>
    </div>
  );
}
