import { AreaChart, Area, ResponsiveContainer, YAxis } from "recharts";
import type { SeriesPoint } from "../api/types";

export default function Sparkline({ series, tone = "accent" }: { series: SeriesPoint[]; tone?: "accent" | "ok" | "warn" | "crit" }) {
  const data = series.slice(-60).map((p) => ({ date: p.date, value: p.value }));
  const colorVar = `var(--${tone === "accent" ? "accent" : tone})`;

  return (
    <div style={{ width: "100%", height: 44 }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`spark-${tone}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colorVar} stopOpacity={0.35} />
              <stop offset="100%" stopColor={colorVar} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis domain={["dataMin", "dataMax"]} hide />
          <Area type="monotone" dataKey="value" stroke={colorVar} strokeWidth={1.75} fill={`url(#spark-${tone})`} isAnimationActive={false} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
