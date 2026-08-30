import { useState } from "react";
import {
  ComposedChart,
  Line,
  Area,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceArea,
} from "recharts";
import type { SeriesPoint } from "../api/types";
import "./TimeSeriesChart.css";

type Overlay = "none" | "seasonal" | "resid";

const OVERLAY_LABELS: Record<Overlay, string> = { none: "None", seasonal: "Seasonal", resid: "Residual" };

export default function TimeSeriesChart({
  series,
  highlightStart,
  highlightEnd,
}: {
  series: SeriesPoint[];
  highlightStart?: string;
  highlightEnd?: string;
}) {
  const [overlay, setOverlay] = useState<Overlay>("none");
  const data = series.slice(-120).map((p) => ({ ...p, baseline: p.trend + p.seasonal }));

  return (
    <div className="ts-chart">
      <div className="ts-toggle">
        <span className="ts-toggle-label">Extra overlay:</span>
        {(["none", "seasonal", "resid"] as Overlay[]).map((o) => (
          <button key={o} className={`btn-secondary ${overlay === o ? "active" : ""}`} onClick={() => setOverlay(o)}>
            {OVERLAY_LABELS[o]}
          </button>
        ))}
      </div>
      <div className="ts-legend">
        <span>
          <i className="ts-swatch ts-swatch-actual" /> Actual
        </span>
        <span>
          <i className="ts-swatch ts-swatch-baseline" /> Expected baseline
        </span>
        <span>
          <i className="ts-swatch ts-swatch-ci" /> Confidence interval
        </span>
        {highlightStart && (
          <span>
            <i className="ts-swatch ts-swatch-anomaly" /> Anomaly window
          </span>
        )}
      </div>
      <div style={{ width: "100%", height: 280 }}>
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
            <defs>
              <linearGradient id="ts-value-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.22} />
                <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: "var(--mute)", fontFamily: "IBM Plex Mono, monospace" }}
              tickLine={false}
              axisLine={{ stroke: "var(--line)" }}
              minTickGap={40}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--mute)", fontFamily: "IBM Plex Mono, monospace" }}
              tickLine={false}
              axisLine={false}
              width={56}
            />
            <Tooltip
              contentStyle={{
                background: "var(--paper)",
                border: "1px solid var(--line)",
                borderRadius: 8,
                fontSize: 12.5,
                fontFamily: "IBM Plex Mono, monospace",
              }}
              labelStyle={{ color: "var(--mute)" }}
            />
            {highlightStart && highlightEnd && (
              <ReferenceArea x1={highlightStart} x2={highlightEnd} fill="var(--warn)" fillOpacity={0.1} strokeOpacity={0} />
            )}
            {/* Confidence band — a real interval computed backend-side from historical residual
                std, not invented in the browser. Recharts draws a range area from a dataKey
                that returns [low, high]. */}
            <Area
              dataKey={(p: SeriesPoint) => [p.ci_lower, p.ci_upper]}
              stroke="none"
              fill="var(--line-strong)"
              fillOpacity={0.35}
              isAnimationActive={false}
              activeDot={false}
            />
            <Line dataKey="baseline" stroke="var(--ink-soft)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
            {overlay === "resid" && <Bar dataKey="resid" fill="var(--accent-line)" radius={[2, 2, 0, 0]} />}
            {overlay === "seasonal" && (
              <Line dataKey="seasonal" stroke="var(--accent-ink)" strokeWidth={1.25} strokeDasharray="2 2" dot={false} isAnimationActive={false} />
            )}
            <Area
              type="monotone"
              dataKey="value"
              stroke="var(--accent)"
              strokeWidth={2}
              fill="url(#ts-value-fill)"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
