/**
 * Builds the game log: one chronological list mixing games already played (with
 * the player's stat line) and games still to come, plus the bye week for NFL.
 */

import type { PlayerGameStatsEntry, ScheduleEntry, TeamSummary } from "./api";

export interface LogRow {
  key: string;
  kind: "played" | "upcoming" | "bye";
  gameId: number | null;
  date: string | null;
  week: number | null;
  status: string;
  opponent: TeamSummary | null;
  isHome: boolean | null;
  teamScore: number | null;
  opponentScore: number | null;
  result: "W" | "L" | "T" | null;
  /** The player's stat line; null for upcoming games and games with no line (e.g. missed). */
  entry: PlayerGameStatsEntry | null;
}

function fromSchedule(game: ScheduleEntry, entry: PlayerGameStatsEntry | null): LogRow {
  return {
    key: `game-${game.game_id}`,
    kind: game.status === "final" ? "played" : "upcoming",
    gameId: game.game_id,
    date: game.game_date,
    week: game.week,
    status: game.status,
    opponent: game.opponent,
    isHome: game.is_home,
    teamScore: game.team_score,
    opponentScore: game.opponent_score,
    result: game.result,
    entry,
  };
}

function fromEntry(entry: PlayerGameStatsEntry): LogRow {
  return {
    key: `game-${entry.game_id}`,
    kind: entry.status === "final" ? "played" : "upcoming",
    gameId: entry.game_id,
    date: entry.game_date,
    week: entry.week,
    status: entry.status,
    opponent: entry.opponent,
    isHome: entry.is_home,
    teamScore: entry.team_score,
    opponentScore: entry.opponent_score,
    result: entry.result,
    entry,
  };
}

/**
 * @param entries every game the player has a stat line for (any order)
 * @param schedule the team's games this season, played and upcoming
 * @param byeWeek the team's bye week, if it has one; shown as a row between weeks
 *
 * The log is this season only, from its first game: stat lines from earlier
 * seasons stay in the chart and averages but aren't listed. With no schedule to
 * go by (a player without a team) the stat lines themselves are listed instead.
 */
export function buildLogRows(
  entries: PlayerGameStatsEntry[],
  schedule: ScheduleEntry[],
  byeWeek: number | null,
): LogRow[] {
  if (schedule.length === 0) {
    return entries
      .map(fromEntry)
      .sort((a, b) => Date.parse(a.date ?? "") - Date.parse(b.date ?? ""));
  }

  const entryByGame = new Map(entries.map((entry) => [entry.game_id, entry]));
  const rows = schedule
    .map((game) => fromSchedule(game, entryByGame.get(game.game_id) ?? null))
    .sort((a, b) => Date.parse(a.date ?? "") - Date.parse(b.date ?? ""));

  if (byeWeek === null) return rows;

  // The bye goes before the first game of a later week, or after the last game.
  const beforeIndex = rows.findIndex((row) => row.week !== null && row.week > byeWeek);
  const bye: LogRow = {
    key: "bye",
    kind: "bye",
    gameId: null,
    date: null,
    week: byeWeek,
    status: "bye",
    opponent: null,
    isHome: null,
    teamScore: null,
    opponentScore: null,
    result: null,
    entry: null,
  };
  if (beforeIndex === -1) return [...rows, bye];
  return [...rows.slice(0, beforeIndex), bye, ...rows.slice(beforeIndex)];
}
