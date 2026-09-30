"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AccuracyResponse } from "@/lib/api";
import {
  chartRows,
  formatMiss,
  orderedSources,
  sourceColor,
  sourceLabel,
  type ChartRow,
} from "@/lib/accuracy";

interface AccuracyChartProps {
  report: AccuracyResponse;
}

/**
 * Each source's average miss per week, in fantasy points, lower is better, all measured on the
 * same player-games. A table view carries the same numbers for anyone who can't or won't use the
 * chart.
 */
export default function AccuracyChart({ report }: AccuracyChartProps) {
  const [asTable, setAsTable] = useState(false);
  const sources = orderedSources(report.sources);
  const rows = chartRows(report);
  const single = rows.length === 1;

  return (
    <section
      aria-label="Average miss by week"
      className="rounded-2xl border border-line bg-surface shadow-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-4 sm:px-5">
        <div>
          <h2 className="font-display text-xl font-semibold uppercase tracking-[0.06em]">
            Average miss by week
          </h2>
          <p className="text-[12.5px] text-ink-3">
            Fantasy points between the projection and what happened. Lower is better.
          </p>
        </div>
        <button
          type="button"
          aria-pressed={asTable}
          onClick={() => setAsTable((value) => !value)}
          className="rounded-[10px] border border-line bg-surface-2 px-3 py-1.5 text-[13px] font-semibold text-ink-2 hover:text-ink"
        >
          {asTable ? "Show chart" : "Show table"}
        </button>
      </div>

      <ul aria-label="Legend" className="flex flex-wrap gap-x-5 gap-y-1 px-4 pt-3 sm:px-5">
        {sources.map((source) => (
          <li key={source} className="inline-flex items-center gap-2 text-[13px] text-ink-2">
            <svg width="22" height="10" aria-hidden="true">
              <line x1="0" y1="5" x2="22" y2="5" stroke={sourceColor(source)} strokeWidth="3" strokeLinecap="round" />
            </svg>
            <span className="font-semibold text-ink">{sourceLabel(source)}</span>
            <span className="text-ink-3">avg {formatMiss(report.overall[source]?.mae)}</span>
          </li>
        ))}
      </ul>

      {asTable ? (
        <div className="overflow-x-auto px-4 pb-4 pt-3 sm:px-5">
          <table className="w-full min-w-[320px] border-collapse text-sm">
            <caption className="sr-only">Average miss in fantasy points, by week</caption>
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-3">
                <th scope="col" className="py-2 pr-3 font-semibold">Week</th>
                <th scope="col" className="py-2 pr-3 text-right font-semibold">Players</th>
                {sources.map((source) => (
                  <th key={source} scope="col" className="py-2 pr-3 text-right font-semibold">
                    {sourceLabel(source)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-b border-line-2">
                  <th scope="row" className="py-2 pr-3 text-left font-medium">{row.label}</th>
                  <td className="py-2 pr-3 text-right tabular-nums text-ink-2">{row.n}</td>
                  {sources.map((source) => (
                    <td key={source} className="py-2 pr-3 text-right tabular-nums">
                      {formatMiss(row[source] as number)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          className="px-2 pb-3.5 pt-2"
          role="img"
          aria-label={`Average miss in fantasy points by week for ${sources
            .map((source) => `${sourceLabel(source)} ${formatMiss(report.overall[source]?.mae)}`)
            .join(", ")}`}
        >
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={rows} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--line-2)" />
              <XAxis
                dataKey="label"
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--ink-3)", fontSize: 11 }}
                padding={{ left: 24, right: 24 }}
              />
              <YAxis
                width={40}
                domain={[0, "auto"]}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--ink-3)", fontSize: 11 }}
                tickFormatter={(value: number) => formatMiss(value)}
              />
              <Tooltip
                cursor={{ stroke: "var(--ink-3)", strokeDasharray: "4 4" }}
                content={<ChartTooltip sources={sources} />}
              />
              {sources.map((source) => (
                <Line
                  key={source}
                  type="monotone"
                  dataKey={source}
                  stroke={sourceColor(source)}
                  strokeWidth={2}
                  dot={{ r: single ? 5 : 4, strokeWidth: 2, stroke: "var(--surface)", fill: sourceColor(source) }}
                  activeDot={{ r: 6, strokeWidth: 2, stroke: "var(--surface)" }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function ChartTooltip({
  active,
  payload,
  sources,
}: {
  active?: boolean;
  payload?: { payload: ChartRow }[];
  sources: string[];
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;

  return (
    <div className="rounded-lg bg-ink px-3 py-2 text-xs leading-snug text-surface shadow-lg">
      <div className="mb-1 opacity-80">
        {row.label} · {row.n} player-games
      </div>
      {sources.map((source) => (
        <div key={source} className="flex items-center gap-2">
          <svg width="14" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="14" y2="4" stroke={sourceColor(source)} strokeWidth="3" strokeLinecap="round" />
          </svg>
          <b className="font-display text-lg leading-tight tabular-nums">
            {formatMiss(row[source] as number)}
          </b>
          <span className="opacity-80">{sourceLabel(source)}</span>
        </div>
      ))}
    </div>
  );
}
