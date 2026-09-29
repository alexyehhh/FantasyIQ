"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import PlayerAvatar from "@/components/PlayerAvatar";
import TeamLogo from "@/components/TeamLogo";
import { getTopScorers, type Sport, type TopScorerEntry } from "@/lib/api";
import { displayPosition } from "@/lib/positions";
import { FPTS, STAT_LABELS, formatStat, profileFor } from "@/lib/stats";
import { usePolling } from "@/lib/usePolling";

const SPORTS: Sport[] = ["NFL", "NBA"];
export const TOP_SCORERS_COUNT = 25;
export const ROTATE_MS = 5000;

const RESULT_WORD = { W: "Won", L: "Lost", T: "Tied" } as const;

/** The top 25 actual fantasy scorers this week (NFL) or day (NBA), one at a time, changing
 * automatically every 5 seconds; the dots below jump straight to a player and reset the timer.
 * Re-fetches in the background every 30s (see usePolling) so a live game's growing stat line
 * shows up without a page reload. */
export default function TopScorersList() {
  const [sport, setSport] = useState<Sport>("NFL");
  const [items, setItems] = useState<TopScorerEntry[]>([]);
  const [week, setWeek] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const requestId = useRef(0);

  const load = useCallback(
    (silent = false) => {
      const id = ++requestId.current;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      getTopScorers(sport, TOP_SCORERS_COUNT)
        .then((res) => {
          if (id !== requestId.current) return;
          setItems(res.items);
          setWeek(res.week);
          setIndex((current) => Math.min(current, Math.max(res.items.length - 1, 0)));
        })
        .catch((err: Error) => {
          if (id === requestId.current && !silent) setError(err.message);
        })
        .finally(() => {
          if (id === requestId.current && !silent) setLoading(false);
        });
    },
    [sport],
  );

  useEffect(() => {
    setIndex(0);
    load();
  }, [load]);

  usePolling(() => load(true));

  useEffect(() => {
    if (items.length < 2) return;
    const timer = setInterval(() => {
      setIndex((current) => (current + 1) % items.length);
    }, ROTATE_MS);
    return () => clearInterval(timer);
  }, [items]);

  const active = items[index] ?? null;
  const profile = active ? profileFor(active.sport, active.position) : null;
  const tiles = profile ? [FPTS, ...profile.tiles.slice(0, 3)] : [];

  return (
    <section aria-label="Top scorers this week" className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-bold uppercase leading-none tracking-wide">
            Top scorers{sport === "NFL" && week ? ` · Week ${week}` : ""}
          </h2>
          <p className="mt-1 text-xs text-ink-3">
            The top {TOP_SCORERS_COUNT} actual fantasy scores {sport === "NFL" ? "this week" : "today"}
            {active ? ` · #${index + 1} of ${items.length}` : ""}.
          </p>
        </div>
        <div role="group" aria-label="Sport" className="flex rounded-[10px] bg-surface-2 p-1">
          {SPORTS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={sport === option}
              onClick={() => setSport(option)}
              className={`h-7 rounded-lg px-3 text-xs font-bold ${
                sport === option ? "bg-accent text-on-accent" : "text-ink-3 hover:text-ink"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-1 flex-col justify-center gap-6 rounded-xl border border-line-2 px-5 py-6">
        {loading ? (
          <p role="status" className="py-8 text-center text-sm text-ink-3">
            Loading…
          </p>
        ) : error ? (
          <p role="alert" className="py-8 text-center text-sm text-bad">
            {error}
          </p>
        ) : !active ? (
          <p role="status" className="py-8 text-center text-sm text-ink-3">
            No games have finished {sport === "NFL" ? "this week" : "yet this season"}.
          </p>
        ) : (
          <>
            <div className="flex items-center gap-4">
              <PlayerAvatar
                size="xl"
                headshotUrl={active.headshot_url}
                teamColor={active.team?.primary_color ?? null}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-ink-3">
                  {active.team && <TeamLogo team={active.team} className="h-4 w-4" />}
                  <span>
                    {displayPosition(active.position) ?? "–"}
                    {active.team ? ` · ${active.team.abbreviation}` : ""}
                  </span>
                </div>
                <h3 className="my-0.5 truncate font-display text-3xl font-bold uppercase leading-[0.95] tracking-[0.01em]">
                  {active.name}
                </h3>
                <div className="text-sm text-ink-3">
                  {active.opponent
                    ? `${active.is_home ? "vs" : "@"} ${active.opponent.abbreviation}`
                    : "No opponent on record"}
                  {active.result && (
                    <>
                      {" "}
                      · {RESULT_WORD[active.result]} {active.team_score}-{active.opponent_score}
                    </>
                  )}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {tiles.map((key, i) => {
                const label = STAT_LABELS[key];
                const value = key === FPTS ? active.fantasy_points : (active.stats[key] ?? 0);
                return (
                  <div
                    key={key}
                    className={`rounded-lg py-3 text-center ${i === 0 ? "bg-accent-soft" : "bg-surface-2"}`}
                  >
                    <div className="text-[10.5px] font-bold uppercase tracking-[0.06em] text-ink-3">
                      {label.abbr}
                    </div>
                    <div
                      className={`font-display text-3xl font-bold leading-tight ${
                        i === 0 ? "text-accent" : "text-ink"
                      }`}
                    >
                      {formatStat(value)}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {items.length > 1 && (
        <div
          role="tablist"
          aria-label="Featured players"
          className="mt-3 flex flex-wrap items-center justify-center gap-1"
        >
          {items.map((item, i) => (
            <button
              key={`${item.id}-${i}`}
              type="button"
              role="tab"
              aria-selected={i === index}
              aria-label={item.name}
              onClick={() => setIndex(i)}
              className={`h-1.5 rounded-full transition-all ${
                i === index ? "w-4 bg-accent" : "w-1.5 bg-line hover:bg-ink-3"
              }`}
            />
          ))}
        </div>
      )}
    </section>
  );
}
