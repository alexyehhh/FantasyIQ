"use client";

import PlayerAvatar from "@/components/PlayerAvatar";
import type { ProjectionEntry } from "@/lib/api";
import { isLocked, matchupLine, points } from "@/lib/startSit";

interface ProjectionListProps {
  entries: ProjectionEntry[];
  /** The rank of the first entry (a later page starts further down). */
  startRank?: number;
  loading: boolean;
  error: string | null;
  empty: string;
  pickedKeys: Set<string>;
  savedKeys: Set<string>;
  onTogglePicked: (entry: ProjectionEntry) => void;
  onToggleSaved: (entry: ProjectionEntry) => void;
}

const PER_COLUMN = 10;
const key = (entry: { kind: string; id: number }) => `${entry.kind}:${entry.id}`;

function Check({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`grid h-6 w-6 flex-none place-items-center rounded-full border-2 ${
        on ? "border-accent bg-accent text-on-accent" : "border-line text-transparent"
      }`}
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m5 12 5 5 9-10" />
      </svg>
    </span>
  );
}

/** Ranked rows in columns of ten: click a row to add it to the comparison, the star saves it. */
export default function ProjectionList({
  entries,
  startRank = 1,
  loading,
  error,
  empty,
  pickedKeys,
  savedKeys,
  onTogglePicked,
  onToggleSaved,
}: ProjectionListProps) {
  if (error) {
    return <p role="alert" className="p-6 text-bad">{error}</p>;
  }
  if (loading && entries.length === 0) {
    return <p role="status" className="p-6 text-ink-3">Loading projections…</p>;
  }
  if (entries.length === 0) {
    return <p className="p-6 text-ink-3">{empty}</p>;
  }

  const columns: ProjectionEntry[][] = [];
  for (let start = 0; start < entries.length; start += PER_COLUMN) {
    columns.push(entries.slice(start, start + PER_COLUMN));
  }

  return (
    <div
      aria-busy={loading}
      className={`grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3 ${loading ? "opacity-60" : ""}`}
    >
      {columns.map((column, columnIndex) => (
        <ol key={columnIndex} className="overflow-hidden rounded-xl border border-line bg-surface">
          {column.map((entry, index) => {
            const picked = pickedKeys.has(key(entry));
            const saved = savedKeys.has(key(entry));
            const rank = startRank + columnIndex * PER_COLUMN + index;
            return (
              <li key={key(entry)} className="flex items-center border-b border-line-2 last:border-b-0">
                <button
                  type="button"
                  aria-pressed={picked}
                  aria-label={`${picked ? "Remove" : "Add"} ${entry.name} ${picked ? "from" : "to"} the comparison`}
                  onClick={() => onTogglePicked(entry)}
                  className={`flex min-w-0 flex-1 items-center gap-3 px-3 py-2.5 text-left hover:bg-surface-2 ${picked ? "bg-accent-soft" : ""}`}
                >
                  <span className="w-6 flex-none text-sm font-semibold tabular-nums text-ink-3">{rank}.</span>
                  <PlayerAvatar headshotUrl={entry.headshot_url} teamColor={entry.team?.primary_color ?? null} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{entry.name}</span>
                    <span className="block truncate text-xs text-ink-3">
                      {matchupLine(entry)}
                      {entry.injury_status ? ` · ${entry.injury_status}` : ""}
                      {isLocked(entry) && (
                        <span className="font-semibold text-warn">
                          {" · "}
                          {entry.game?.status === "final" ? "Final" : "Live"}
                        </span>
                      )}
                    </span>
                  </span>
                  <span className="flex-none text-right">
                    <span className="block text-base font-bold tabular-nums">{points(entry.fantasy_points)}</span>
                    <span className="block text-[11px] text-ink-3">proj.</span>
                  </span>
                  <Check on={picked} />
                </button>
                <button
                  type="button"
                  aria-pressed={saved}
                  aria-label={saved ? `Remove ${entry.name} from My Team` : `Save ${entry.name} to My Team`}
                  onClick={() => onToggleSaved(entry)}
                  className={`mr-2 grid h-8 w-8 flex-none place-items-center rounded-full hover:bg-surface-2 ${saved ? "text-warn" : "text-ink-3"}`}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z" fill={saved ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                  </svg>
                </button>
              </li>
            );
          })}
        </ol>
      ))}
    </div>
  );
}
