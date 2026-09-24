"use client";

import { useRef, useState } from "react";
import type { Sport } from "@/lib/api";
import { formatGameDate, formatGameTime } from "@/lib/format";
import type { LogRow } from "@/lib/gameLog";
import {
  FPTS,
  KICKS,
  NBA_LOG_COLUMNS,
  NFL_LOG_COLUMNS,
  STAT_LABELS,
  formatKicks,
  formatStat,
  statValue,
  type LogColumn,
} from "@/lib/stats";

interface GameLogProps {
  sport: Sport;
  /** This season from its first game: results, then upcoming games; NFL includes the bye week. */
  rows: LogRow[];
  /** The stat currently charted, highlighted down its column. */
  selectedStat: string;
  /** False for positions whose stat lines we don't store: the log is then just the schedule. */
  showStats?: boolean;
  /** The stat columns to show; defaults to the sport's player columns. */
  columns?: LogColumn[];
  /** Stats where fewer is better, so their best game isn't the highest one. */
  negativeStats?: ReadonlySet<string>;
  /** The "FPTS uses ... scoring" line under the table, if the scoring is known. */
  scoringNote?: string | null;
}

// A zero is dimmed to a dash in an NFL log, except where zero is the result: fantasy points, and a
// defense's shutout or its yards allowed.
const NEVER_DIMMED = new Set([FPTS, "points_allowed", "yards_allowed"]);

// A full NBA season is 82 games, so the log shows one page of 20 at a time. Pages are
// counted from the season's first game: games 1-20, 21-40, and so on.
const PAGE_SIZE = 20;

const HEAD = "px-2.5 py-2.5 text-[11px] font-bold uppercase tracking-[0.08em] text-ink-3";
const CELL = "whitespace-nowrap px-2.5 py-[11px] text-right tabular-nums";
const PAGER_BUTTON =
  "rounded-[9px] border border-line px-4 py-2 text-[13px] font-semibold enabled:hover:border-accent enabled:hover:text-accent disabled:cursor-not-allowed disabled:opacity-45";
const META_CELL = "whitespace-nowrap border-b border-line-2 px-2.5 py-[11px] text-left group-hover:bg-surface-2";

/**
 * Everything when it fits on one page. Otherwise the first page that isn't yet
 * full of results: as each 20 games are played, the log moves on to the next 20.
 * Once the season is over, the last page.
 */
function openingPage(rows: LogRow[]): [number, number] {
  if (rows.length <= PAGE_SIZE) return [0, rows.length];
  const firstUpcoming = rows.findIndex((row) => row.kind === "upcoming");
  const anchor = firstUpcoming === -1 ? rows.length - 1 : firstUpcoming;
  const start = Math.floor(anchor / PAGE_SIZE) * PAGE_SIZE;
  return [start, Math.min(rows.length, start + PAGE_SIZE)];
}

export default function GameLog({
  sport,
  rows,
  selectedStat,
  showStats = true,
  columns: columnsProp,
  negativeStats,
  scoringNote,
}: GameLogProps) {
  const [[start, end], setWindow] = useState(() => openingPage(rows));
  const section = useRef<HTMLElement>(null);
  // The pager sits below the table, so a new page should start back at the top of the log.
  const turnPage = (from: number, to: number) => {
    setWindow([from, to]);
    section.current?.scrollIntoView({ block: "start" });
  };
  const defaultColumns = sport === "NBA" ? NBA_LOG_COLUMNS : NFL_LOG_COLUMNS;
  const columns = !showStats ? [] : (columnsProp ?? defaultColumns);
  const lowerIsBetter = negativeStats?.has(selectedStat) ?? false;
  const groups: { name: string; span: number }[] = [];
  for (const column of columns) {
    const last = groups[groups.length - 1];
    if (column.group && last?.name === column.group) last.span += 1;
    else if (column.group) groups.push({ name: column.group, span: 1 });
  }
  const grouped = groups.length > 0;
  const played = rows.filter((row) => row.kind === "played").length;
  const upcoming = rows.filter((row) => row.kind === "upcoming").length;
  const best = Math.max(
    ...rows.map((row) => (row.entry ? statValue(row.entry, selectedStat) : -Infinity)),
  );
  const startsGroup = (index: number) =>
    grouped && index > 0 && columns[index - 1].group !== columns[index].group;
  const selected = (key: string) => (key === selectedStat ? "bg-accent-soft" : "");
  const visible = rows.slice(start, end);
  const previousCount = Math.min(PAGE_SIZE, start);
  const nextCount = Math.min(PAGE_SIZE, rows.length - end);

  return (
    <section
      ref={section}
      aria-label="Game log"
      className="rounded-2xl border border-line bg-surface shadow-panel"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 px-4 pt-4 sm:px-5">
        <h2 className="font-display text-xl font-semibold uppercase tracking-[0.06em]">
          Game log
        </h2>
        <span className="text-[12.5px] text-ink-3">
          {played} played · {upcoming} upcoming
        </span>
      </div>

      <div className="mt-3 overflow-x-auto border-t border-line">
        <table className="w-full min-w-[560px] border-separate border-spacing-0 text-[13px]">
          <thead className="bg-surface-2">
            {grouped && (
              <tr>
                <th rowSpan={2} className={`${HEAD} sticky left-0 bg-surface-2 pl-4 text-left sm:pl-5`}>
                  Date
                </th>
                <th rowSpan={2} className={`${HEAD} text-left`}>
                  Opp
                </th>
                <th rowSpan={2} className={`${HEAD} text-left`}>
                  Result
                </th>
                {groups.map((group) => (
                  <th
                    key={group.name}
                    colSpan={group.span}
                    className="border-l border-line px-2.5 py-1.5 text-center text-[11px] font-bold uppercase tracking-[0.1em] text-ink-2"
                  >
                    {group.name}
                  </th>
                ))}
              </tr>
            )}
            <tr>
              {!grouped && (
                <>
                  <th className={`${HEAD} sticky left-0 bg-surface-2 pl-4 text-left sm:pl-5`}>
                    Date
                  </th>
                  <th className={`${HEAD} text-left`}>Opp</th>
                  <th className={`${HEAD} text-left`}>Result</th>
                </>
              )}
              {columns.map((column, index) => (
                <th
                  key={column.key}
                  className={`${HEAD} border-b border-line text-right ${selected(column.key)} ${
                    startsGroup(index) ? "border-l" : ""
                  }`}
                >
                  {STAT_LABELS[column.key].abbr}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) =>
              row.kind === "bye" ? (
                <tr key={row.key}>
                  <td
                    colSpan={3 + columns.length}
                    className="border-b border-line-2 bg-surface-2 px-4 py-2.5 text-center text-xs font-bold uppercase tracking-[0.1em] text-ink-3 sm:px-5"
                  >
                    Week {row.week} · Bye
                  </td>
                </tr>
              ) : (
                <tr key={row.key} className="group">
                  <td className="sticky left-0 whitespace-nowrap border-b border-line-2 bg-surface py-[11px] pl-4 pr-2.5 text-left font-semibold group-hover:bg-surface-2 sm:pl-5">
                    {sport === "NFL" && row.week !== null && (
                      <span className="mr-1.5 inline-block w-[38px] text-[11px] font-medium text-ink-3">Wk {row.week}</span>
                    )}
                    {row.date ? formatGameDate(row.date) : "—"}
                  </td>
                  <td className={META_CELL}>
                    {row.opponent
                      ? `${row.isHome ? "vs" : "@"} ${row.opponent.abbreviation}`
                      : "—"}
                  </td>
                  <td className={`${META_CELL} tabular-nums`}>
                    {row.kind === "upcoming" ? (
                      <span className="text-ink-2">
                        {row.status === "in_progress" ? "Live" : row.date ? formatGameTime(row.date) : "—"}
                      </span>
                    ) : row.result && row.teamScore !== null ? (
                      <>
                        <span
                          className={`font-bold ${row.result === "W" ? "text-good" : row.result === "L" ? "text-bad" : "text-ink-2"}`}
                        >
                          {row.result}
                        </span>{" "}
                        <span className="text-ink-2">
                          {row.teamScore}–{row.opponentScore}
                        </span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  {row.entry
                    ? columns.map((column, index) => {
                        if (column.key === KICKS) {
                          return (
                            <td
                              key={column.key}
                              className={`${CELL} border-b border-line-2 group-hover:bg-surface-2 ${
                                startsGroup(index) ? "border-l border-l-line" : ""
                              }`}
                            >
                              {formatKicks(row.entry!.kicks)}
                            </td>
                          );
                        }
                        const value = statValue(row.entry!, column.key);
                        const dim = sport === "NFL" && !NEVER_DIMMED.has(column.key) && value === 0;
                        const isBest =
                          column.key === selectedStat &&
                          !lowerIsBetter &&
                          value === best &&
                          best > 0;
                        return (
                          <td
                            key={column.key}
                            className={`${CELL} border-b border-line-2 group-hover:bg-surface-2 ${selected(column.key)} ${
                              startsGroup(index) ? "border-l border-l-line" : ""
                            } ${column.key === FPTS ? "font-bold" : ""} ${
                              isBest ? "font-bold text-accent" : ""
                            } ${dim ? "text-ink-3 opacity-60" : ""}`}
                          >
                            {dim ? "–" : formatStat(value)}
                          </td>
                        );
                      })
                    : columns.length > 0 && (
                        <td
                          colSpan={columns.length}
                          className="border-b border-line-2 px-2.5 py-[11px] text-left text-xs italic text-ink-3 group-hover:bg-surface-2"
                        >
                          {row.kind === "upcoming"
                            ? row.status === "in_progress"
                              ? "In progress"
                              : "Upcoming"
                            : "No stats recorded"}
                        </td>
                      )}
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>

      {rows.length > PAGE_SIZE && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5 sm:px-5">
          <button
            type="button"
            disabled={previousCount === 0}
            onClick={() => turnPage(start - previousCount, start)}
            className={PAGER_BUTTON}
          >
            ‹ Previous {previousCount || PAGE_SIZE}
          </button>
          <span className="text-[12.5px] text-ink-3">
            Games {start + 1}–{end} of {rows.length}
          </span>
          <button
            type="button"
            disabled={nextCount === 0}
            onClick={() => turnPage(end, end + nextCount)}
            className={PAGER_BUTTON}
          >
            Next {nextCount || PAGE_SIZE} ›
          </button>
        </div>
      )}
      {showStats && scoringNote && (
        <p className="border-t border-line px-4 py-3 text-xs text-ink-3 sm:px-5">{scoringNote}</p>
      )}
    </section>
  );
}
