"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import TeamLogo from "@/components/TeamLogo";
import { getScoreboard, type ScoreboardGame } from "@/lib/api";
import { formatGameDateTime } from "@/lib/format";
import { usePolling } from "@/lib/usePolling";

export const ROTATE_MS = 5000;

/** This week's NFL games, one at a time, changing automatically every 5 seconds; the dots
 * below jump straight to a game and reset the timer. Re-fetches in the background every 30s
 * (see usePolling) so a live game's score shows up without a page reload. */
export default function ScoresStrip() {
  const [games, setGames] = useState<ScoreboardGame[]>([]);
  const [week, setWeek] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const requestId = useRef(0);

  const load = useCallback((silent = false) => {
    const id = ++requestId.current;
    if (!silent) setError(null);
    getScoreboard("NFL")
      .then((res) => {
        if (id !== requestId.current) return;
        setGames(res.games);
        setWeek(res.week);
        setIndex((current) => Math.min(current, Math.max(res.games.length - 1, 0)));
      })
      .catch((err: Error) => {
        if (id === requestId.current && !silent) setError(err.message);
      })
      .finally(() => {
        if (id === requestId.current && !silent) setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  usePolling(() => load(true));

  useEffect(() => {
    if (games.length < 2) return;
    const timer = setInterval(() => {
      setIndex((current) => (current + 1) % games.length);
    }, ROTATE_MS);
    return () => clearInterval(timer);
  }, [games]);

  const game = games[index] ?? null;

  return (
    <section aria-label="This week's scores" className="flex h-full flex-col">
      <div>
        <h2 className="font-display text-xl font-bold uppercase leading-none tracking-wide">
          Scores{week ? ` · Week ${week}` : ""}
        </h2>
        {game && (
          <p className="mt-1 text-xs text-ink-3">
            Game {index + 1} of {games.length}
          </p>
        )}
      </div>

      <div className="mt-3 flex flex-1 flex-col justify-center rounded-xl border border-line-2 px-4 py-5">
        {loading ? (
          <p role="status" className="py-8 text-center text-sm text-ink-3">
            Loading…
          </p>
        ) : error ? (
          <p role="alert" className="py-8 text-center text-sm text-bad">
            {error}
          </p>
        ) : !game ? (
          <p role="status" className="py-8 text-center text-sm text-ink-3">
            No games scheduled yet.
          </p>
        ) : (
          <div className="flex items-center justify-center gap-5">
            <div className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center">
              <TeamLogo team={game.away_team} className="h-12 w-12" />
              <span className="truncate text-sm font-semibold">{game.away_team.abbreviation}</span>
              <span className="font-display text-3xl font-bold tabular-nums">
                {game.away_score ?? "–"}
              </span>
            </div>
            <div className="flex-none text-center">
              <div className="text-xs font-semibold uppercase tracking-wide text-ink-3">
                {game.status === "final"
                  ? "Final"
                  : game.status === "in_progress"
                    ? "Live"
                    : formatGameDateTime(game.start_time)}
              </div>
            </div>
            <div className="flex min-w-0 flex-1 flex-col items-center gap-2 text-center">
              <TeamLogo team={game.home_team} className="h-12 w-12" />
              <span className="truncate text-sm font-semibold">{game.home_team.abbreviation}</span>
              <span className="font-display text-3xl font-bold tabular-nums">
                {game.home_score ?? "–"}
              </span>
            </div>
          </div>
        )}
      </div>

      {games.length > 1 && (
        <div
          role="tablist"
          aria-label="This week's games"
          className="mt-3 flex flex-wrap items-center justify-center gap-1"
        >
          {games.map((g, i) => (
            <button
              key={g.game_id}
              type="button"
              role="tab"
              aria-selected={i === index}
              aria-label={`${g.away_team.abbreviation} at ${g.home_team.abbreviation}`}
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
