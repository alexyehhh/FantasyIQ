import type { PlayerGameStatsEntry, Sport } from "@/lib/api";
import { STAT_LABELS, average, formatStat, statValue } from "@/lib/stats";

interface AveragesTableProps {
  sport: Sport;
  /** Most recent game first. */
  entries: PlayerGameStatsEntry[];
  rows: string[];
  selectedStat: string;
}

export default function AveragesTable({
  sport,
  entries,
  rows,
  selectedStat,
}: AveragesTableProps) {
  const head = "px-2 py-1.5 text-right text-[11px] font-bold uppercase tracking-[0.08em] text-ink-3";

  return (
    <section
      aria-label="Averages"
      className="rounded-2xl border border-line bg-surface pb-2 shadow-panel"
    >
      <div className="flex items-baseline justify-between px-5 pt-4">
        <h2 className="font-display text-xl font-semibold uppercase tracking-[0.06em]">
          Averages
        </h2>
        <span className="text-[12.5px] text-ink-3">per game</span>
      </div>
      <table className="mt-2.5 w-full border-collapse">
        <thead>
          <tr>
            <th className={`${head} pl-5 text-left`}>Stat</th>
            <th className={head}>L5</th>
            <th className={head}>L10</th>
            <th className={`${head} pr-5`}>All {entries.length}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((key) => {
            const values = entries.map((entry) => statValue(entry, key));
            const isSelected = key === selectedStat;
            const label = STAT_LABELS[key];
            return (
              <tr
                key={key}
                className={isSelected ? "bg-accent-soft font-bold" : "font-medium"}
              >
                <td
                  className={`border-t border-line-2 py-[9px] pl-5 pr-2 text-left font-semibold ${
                    isSelected ? "text-accent" : "text-ink-2"
                  }`}
                >
                  {sport === "NBA" || key === "fpts" ? label.abbr : label.name}
                </td>
                {[values.slice(0, 5), values.slice(0, 10), values].map((slice, index) => (
                  <td
                    key={index}
                    className={`border-t border-line-2 px-2 py-[9px] text-right tabular-nums ${
                      index === 2 ? "pr-5" : ""
                    }`}
                  >
                    {formatStat(average(slice))}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
