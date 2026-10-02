/**
 * The logic behind a player's projection accuracy: naming and coloring the sources, the miss on
 * each game, and averaging the misses to say which source was closer.
 */

import type { AccuracyPlayerGame } from "./api";

const LABELS: Record<string, string> = {
  fantasyiq: "FantasyIQ model",
  sleeper: "Sleeper",
};

export function sourceLabel(name: string): string {
  return LABELS[name] ?? name;
}

/**
 * A source's color, fixed by who it is and never by its rank: our model is the app's violet and
 * every outside source the orange.
 */
export function sourceColor(name: string): string {
  return name === "fantasyiq" ? "var(--series-model)" : "var(--series-other)";
}

/** Our model first, then the others, so legends and tables keep one order. */
export function orderedSources(sources: string[]): string[] {
  return [...sources].sort((a, b) => Number(b === "fantasyiq") - Number(a === "fantasyiq") || a.localeCompare(b));
}

/** Fantasy points with one decimal, "—" when there is nothing to show. */
export function formatMiss(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(1);
}

/** A bias with its sign: "+1.2" projects too high, "−0.4" too low. */
export function formatBias(value: number): string {
  if (Math.abs(value) < 0.05) return "0.0";
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}`;
}

/** A source's miss on one game, projected minus actual: positive ran high. Null with no result. */
export function gameMiss(game: AccuracyPlayerGame, source: string): number | null {
  const projected = game.projected[source];
  return game.actual == null || projected === undefined ? null : projected - game.actual;
}

/** "Week 4" for the NFL, the date for the NBA. */
export function gameLabel(game: AccuracyPlayerGame): string {
  if (game.week != null) return `Week ${game.week}`;
  return new Date(game.start_time).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** The sources that project a game, ours first, for a table's columns. */
export function projectingSources(games: AccuracyPlayerGame[]): string[] {
  return orderedSources([...new Set(games.flatMap((game) => Object.keys(game.projected)))]);
}

export interface SourceAverage {
  source: string;
  /** Average size of the miss in points: lower is better. */
  mae: number;
  /** Average of projected minus actual: positive means it ran high. */
  bias: number;
}

export interface PlayerSummary {
  /** Games the averages cover. */
  n: number;
  averages: SourceAverage[];
  /** The source with the smallest average miss, null when there is nothing to compare or a tie. */
  best: string | null;
}

/**
 * Average each source's miss over the games the player played. Only games every source projected
 * count, so no source is judged on easier ones than another.
 */
export function summarize(games: AccuracyPlayerGame[]): PlayerSummary {
  const sources = projectingSources(games);
  const scored = games.filter(
    (game) => game.actual != null && sources.every((source) => gameMiss(game, source) !== null),
  );
  const averages = sources.map((source) => {
    const misses = scored.map((game) => gameMiss(game, source) as number);
    const total = (values: number[]) => values.reduce((sum, value) => sum + value, 0);
    return {
      source,
      mae: scored.length ? total(misses.map(Math.abs)) / scored.length : 0,
      bias: scored.length ? total(misses) / scored.length : 0,
    };
  });
  const ranked = [...averages].sort((a, b) => a.mae - b.mae);
  const clear = scored.length > 0 && ranked.length > 1 && ranked[1].mae - ranked[0].mae >= 0.05;
  return { n: scored.length, averages, best: clear ? ranked[0].source : null };
}
