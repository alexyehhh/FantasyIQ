import type { ProjectionEntry } from "@/lib/api";
import { points } from "@/lib/startSit";

interface RangePlotProps {
  entries: ProjectionEntry[];
  starterIds: Set<string>;
}

const key = (entry: ProjectionEntry) => `${entry.kind}:${entry.id}`;

/**
 * Every player's likely range on one shared axis: the bar runs from floor to ceiling (one
 * standard deviation either side) and the dot marks the projection. Overlapping bars are close
 * calls; a long bar is a boom-or-bust player.
 */
export default function RangePlot({ entries, starterIds }: RangePlotProps) {
  const scored = entries.filter(
    (entry) => entry.fantasy_points !== null && entry.low !== null && entry.high !== null,
  );
  if (scored.length === 0) return null;

  const lowest = Math.min(0, ...scored.map((entry) => entry.low ?? 0));
  const highest = Math.max(...scored.map((entry) => entry.high ?? 0));
  const span = highest - lowest || 1;
  const at = (value: number) => `${(((value - lowest) / span) * 100).toFixed(2)}%`;

  return (
    <div
      role="img"
      aria-label={`Likely range of fantasy points: ${scored
        .map((entry) => `${entry.name} ${points(entry.low)} to ${points(entry.high)}`)
        .join("; ")}`}
      className="space-y-2.5"
    >
      {scored.map((entry) => {
        const starter = starterIds.has(key(entry));
        return (
          <div key={key(entry)} className="grid grid-cols-[minmax(0,110px)_1fr_52px] items-center gap-3 sm:grid-cols-[minmax(0,150px)_1fr_60px]">
            <span className="truncate text-sm font-semibold">{entry.name}</span>
            <div className="relative h-6" aria-hidden="true">
              <div className="absolute left-0 right-0 top-1/2 h-px bg-line" />
              <div
                className={`absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full ${
                  starter ? "bg-accent opacity-30" : "bg-bar-dim opacity-80"
                }`}
                style={{ left: at(entry.low ?? 0), width: `calc(${at(entry.high ?? 0)} - ${at(entry.low ?? 0)})` }}
              />
              <div
                className={`absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface ${
                  starter ? "bg-accent" : "bg-ink-3"
                }`}
                style={{ left: at(entry.fantasy_points ?? 0) }}
              />
            </div>
            <span className="text-right text-sm font-bold tabular-nums">{points(entry.fantasy_points)}</span>
          </div>
        );
      })}
      <div className="grid grid-cols-[minmax(0,110px)_1fr_52px] gap-3 text-[11px] font-semibold text-ink-3 sm:grid-cols-[minmax(0,150px)_1fr_60px]">
        <span />
        <span className="flex justify-between">
          <span>{points(lowest)}</span>
          <span>{points(highest)}</span>
        </span>
        <span />
      </div>
    </div>
  );
}
