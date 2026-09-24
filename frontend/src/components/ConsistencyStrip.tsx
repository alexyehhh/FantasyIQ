import type { PlayerGameStatsEntry, Sport } from "@/lib/api";
import { STAT_LABELS, average, formatStat, statValue } from "@/lib/stats";

interface ConsistencyStripProps {
  sport: Sport;
  /** Most recent game first. */
  entries: PlayerGameStatsEntry[];
  stat: string;
}

const WIDTH = 300;
const HEIGHT = 96;
const PAD = 14;
const BASELINE = 58;
const DOT_RADIUS = 5;

function median(sorted: number[]): number {
  const mid = (sorted.length - 1) / 2;
  return (sorted[Math.floor(mid)] + sorted[Math.ceil(mid)]) / 2;
}

/** Every game as a dot on one axis: how spread out a player's output is, at a glance. */
export default function ConsistencyStrip({ sport, entries, stat }: ConsistencyStripProps) {
  const values = entries.map((entry) => statValue(entry, stat, sport));
  const sorted = [...values].sort((a, b) => a - b);
  const floor = sorted[0];
  const ceiling = sorted[sorted.length - 1];
  const mid = median(sorted);
  const mean = average(values);
  const span = ceiling - floor || 1;
  const x = (value: number) => PAD + ((value - floor) / span) * (WIDTH - PAD * 2);

  // Games with near-identical values stack upward instead of overprinting.
  const placed: { cx: number; level: number }[] = [];
  const dots = values.map((value, index) => {
    const cx = x(value);
    let level = 0;
    while (placed.some((dot) => dot.level === level && Math.abs(dot.cx - cx) < DOT_RADIUS * 2)) {
      level += 1;
    }
    placed.push({ cx, level });
    return { cx, level, latest: index === 0 };
  });

  const statName = STAT_LABELS[stat]?.name ?? stat;

  return (
    <section
      aria-label="Consistency"
      className="rounded-2xl border border-line bg-surface shadow-panel"
    >
      <div className="flex items-baseline justify-between px-5 pt-4">
        <h2 className="font-display text-xl font-semibold uppercase tracking-[0.06em]">
          Consistency
        </h2>
        <span className="text-[12.5px] text-ink-3">
          {statName} · {entries.length} {entries.length === 1 ? "game" : "games"}
        </span>
      </div>
      <div className="px-4 pt-1">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`Spread of ${statName} across ${entries.length} games from ${formatStat(floor)} to ${formatStat(ceiling)}, median ${formatStat(mid)}, average ${formatStat(mean)}`}
          className="block h-auto w-full"
        >
          <line
            x1={PAD}
            x2={WIDTH - PAD}
            y1={BASELINE + 10}
            y2={BASELINE + 10}
            stroke="var(--line)"
            strokeWidth={2}
            strokeLinecap="round"
          />
          {dots.map((dot, index) => (
            <circle
              key={index}
              cx={dot.cx}
              cy={BASELINE - dot.level * 11}
              r={DOT_RADIUS}
              fill="var(--accent)"
              fillOpacity={dot.latest ? 1 : 0.55}
            />
          ))}
          <line
            x1={x(mid)}
            x2={x(mid)}
            y1={BASELINE + 4}
            y2={BASELINE + 16}
            stroke="var(--ink)"
            strokeWidth={2}
          />
          <line
            x1={x(mean)}
            x2={x(mean)}
            y1={BASELINE - 22}
            y2={BASELINE + 16}
            stroke="var(--ink-3)"
            strokeWidth={1.5}
            strokeDasharray="3 3"
          />
          <text x={PAD} y={HEIGHT - 6} fontSize={11} fill="var(--ink-3)" textAnchor="start">
            {formatStat(floor)}
          </text>
          <text x={WIDTH - PAD} y={HEIGHT - 6} fontSize={11} fill="var(--ink-3)" textAnchor="end">
            {formatStat(ceiling)}
          </text>
        </svg>
      </div>
      <dl className="grid grid-cols-4 gap-2 px-5 pb-[18px] text-center">
        {(
          [
            ["Floor", floor],
            ["Median", mid],
            ["Average", mean],
            ["Ceiling", ceiling],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <dd className="font-display text-[26px] font-bold leading-tight tabular-nums">
              {formatStat(value)}
            </dd>
            <dt className="text-[11px] font-bold uppercase tracking-[0.08em] text-ink-3">
              {label}
            </dt>
          </div>
        ))}
      </dl>
    </section>
  );
}
