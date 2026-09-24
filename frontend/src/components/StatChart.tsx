"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PlayerGameStatsEntry, Sport } from "@/lib/api";
import { formatGameDate } from "@/lib/format";
import { STAT_LABELS, average, formatStat, statValue } from "@/lib/stats";

export type ChartRange = 5 | 10 | "all";

interface StatChartProps {
  sport: Sport;
  /** Every game, most recent first, as the API returns them. */
  entries: PlayerGameStatsEntry[];
  stat: string;
  onStatChange: (stat: string) => void;
  /** Stats offered as chips, in display order. */
  statOptions: string[];
  range: ChartRange;
  onRangeChange: (range: ChartRange) => void;
}

// Value labels above the bars stop being readable past this many games.
const MAX_LABELLED_BARS = 12;

interface ChartPoint {
  gameId: number;
  label: string;
  value: number;
  detail: string;
}

export function rangeOptions(total: number): { value: ChartRange; label: string }[] {
  const options: { value: ChartRange; label: string }[] = [];
  if (total > 5) options.push({ value: 5, label: "Last 5" });
  if (total > 10) options.push({ value: 10, label: "Last 10" });
  options.push({ value: "all", label: `All ${total}` });
  return options;
}

export default function StatChart({
  sport,
  entries,
  stat,
  onStatChange,
  statOptions,
  range,
  onRangeChange,
}: StatChartProps) {
  const shown = range === "all" ? entries : entries.slice(0, range);
  // The API is most-recent-first; chart oldest to newest, left to right.
  const points: ChartPoint[] = [...shown].reverse().map((entry) => ({
    gameId: entry.game_id,
    label: formatGameDate(entry.game_date),
    value: statValue(entry, stat, sport),
    detail: [
      formatGameDate(entry.game_date),
      entry.opponent ? `${entry.is_home ? "vs" : "@"} ${entry.opponent.abbreviation}` : null,
      entry.result && entry.team_score !== null && entry.opponent_score !== null
        ? `${entry.result} ${entry.team_score}–${entry.opponent_score}`
        : null,
    ]
      .filter(Boolean)
      .join(" · "),
  }));
  const mean = average(points.map((point) => point.value));
  const options = rangeOptions(entries.length);
  const statName = STAT_LABELS[stat]?.name ?? stat;

  return (
    <section
      aria-label="Game trend"
      className="rounded-2xl border border-line bg-surface shadow-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-4 sm:px-5">
        <h2 className="font-display text-xl font-semibold uppercase tracking-[0.06em]">
          Game trend
        </h2>
        {options.length > 1 && (
          <div
            role="group"
            aria-label="Games shown"
            className="inline-flex gap-0.5 rounded-[10px] border border-line bg-surface-2 p-[3px]"
          >
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={range === option.value}
                onClick={() => onRangeChange(option.value)}
                className={`rounded-[7px] px-3 py-1.5 text-[13px] font-semibold ${
                  range === option.value
                    ? "bg-surface text-ink shadow"
                    : "text-ink-2 hover:text-ink"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div
        role="group"
        aria-label="Stat"
        className="flex gap-2 overflow-x-auto px-4 pb-1 pt-3.5 sm:px-5"
      >
        {statOptions.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={stat === option}
            onClick={() => onStatChange(option)}
            className={`flex-none rounded-full border px-[13px] py-1.5 text-[13px] font-semibold ${
              stat === option
                ? "border-accent bg-accent text-on-accent"
                : "border-line bg-surface text-ink-2 hover:border-accent hover:text-ink"
            }`}
          >
            {STAT_LABELS[option]?.name ?? option}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1 px-4 pt-2 sm:px-5">
        <span className="font-display text-3xl font-bold leading-none tabular-nums">
          {formatStat(mean)}
        </span>
        <span className="text-[12.5px] text-ink-3">
          {statName} per game · {range === "all" ? "all" : "last"} {points.length}
        </span>
        <div className="flex gap-4 text-xs text-ink-3 sm:ml-auto">
          <span className="inline-flex items-center gap-1.5">
            <i className="h-2.5 w-2.5 rounded-[3px] bg-accent" />
            Above avg
          </span>
          <span className="inline-flex items-center gap-1.5">
            <i className="h-2.5 w-2.5 rounded-[3px] bg-bar-dim" />
            Below avg
          </span>
        </div>
      </div>

      <div
        className="px-2 pb-3.5 pt-1.5"
        role="img"
        aria-label={`${statName} over ${points.length} games, average ${formatStat(mean)}`}
      >
        <ResponsiveContainer width="100%" height={270}>
          <BarChart data={points} margin={{ top: 18, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--line-2)" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tick={{ fill: "var(--ink-3)", fontSize: 11 }}
            />
            <YAxis
              width={40}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "var(--ink-3)", fontSize: 11 }}
              tickFormatter={(value: number) => formatStat(value)}
            />
            <Tooltip
              cursor={{ fill: "var(--line-2)" }}
              content={<ChartTooltip statName={statName} />}
            />
            <ReferenceLine
              y={mean}
              stroke="var(--ink-3)"
              strokeDasharray="5 4"
              strokeWidth={1.5}
              label={{
                value: `avg ${formatStat(mean)}`,
                position: "insideTopRight",
                fill: "var(--ink-2)",
                fontSize: 11,
                fontWeight: 700,
              }}
            />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={40}>
              {points.map((point) => (
                <Cell
                  key={point.gameId}
                  fill={point.value >= mean ? "var(--accent)" : "var(--bar-dim)"}
                />
              ))}
              {points.length <= MAX_LABELLED_BARS && (
                <LabelList
                  dataKey="value"
                  position="top"
                  formatter={(value: unknown) => formatStat(Number(value))}
                  style={{ fill: "var(--ink-2)", fontSize: 11, fontWeight: 600 }}
                />
              )}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function ChartTooltip({
  active,
  payload,
  statName,
}: {
  active?: boolean;
  payload?: { payload: ChartPoint }[];
  statName: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;

  return (
    <div className="rounded-lg bg-ink px-3 py-2 text-xs leading-snug text-surface shadow-lg">
      <b className="block font-display text-xl leading-tight tracking-wide">
        {formatStat(point.value)} {statName}
      </b>
      {point.detail}
    </div>
  );
}
