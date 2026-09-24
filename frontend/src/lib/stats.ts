/**
 * Everything the player pages know about how to present a stat line: labels,
 * which stats matter for which position, and the game-log columns. The stats
 * dict the API returns is sport-shaped (see app/schemas/players.py), so this
 * is the one place that maps those raw keys to what a fan expects to read.
 */

import type { PlayerGameStatsEntry, Sport } from "./api";
import { isSpecialTeamer } from "./positions";
import { DEFAULT_SCORING, fantasyPoints } from "./scoring";

export const FPTS = "fpts";

export const STAT_LABELS: Record<string, { name: string; abbr: string }> = {
  [FPTS]: { name: "Fantasy pts", abbr: "FPTS" },
  minutes: { name: "Minutes", abbr: "MIN" },
  points: { name: "Points", abbr: "PTS" },
  rebounds: { name: "Rebounds", abbr: "REB" },
  assists: { name: "Assists", abbr: "AST" },
  steals: { name: "Steals", abbr: "STL" },
  blocks: { name: "Blocks", abbr: "BLK" },
  turnovers: { name: "Turnovers", abbr: "TO" },
  field_goal_attempts: { name: "FG attempts", abbr: "FGA" },
  three_point_attempts: { name: "3PT attempts", abbr: "3PA" },
  passing_completions: { name: "Completions", abbr: "CMP" },
  passing_attempts: { name: "Pass attempts", abbr: "ATT" },
  passing_yards: { name: "Passing yards", abbr: "YDS" },
  passing_touchdowns: { name: "Passing TDs", abbr: "TD" },
  interceptions: { name: "Interceptions", abbr: "INT" },
  rushing_attempts: { name: "Carries", abbr: "ATT" },
  rushing_yards: { name: "Rushing yards", abbr: "YDS" },
  rushing_touchdowns: { name: "Rushing TDs", abbr: "TD" },
  receptions: { name: "Receptions", abbr: "REC" },
  receiving_targets: { name: "Targets", abbr: "TGT" },
  receiving_yards: { name: "Receiving yards", abbr: "YDS" },
  receiving_touchdowns: { name: "Receiving TDs", abbr: "TD" },
  fumbles_lost: { name: "Fumbles lost", abbr: "FUM" },
};

/** Stats where a lower number is better, so a rising trend is bad news. */
export const NEGATIVE_STATS = new Set(["turnovers", "interceptions", "fumbles_lost"]);

export interface StatProfile {
  /** False when the stat lines we store say nothing about this position. */
  tracked: boolean;
  /** The four stats shown beside fantasy points in the header. */
  tiles: string[];
  /** Rows of the averages table and the stat chips above the chart (fantasy points first). */
  rows: string[];
  defaultStat: string;
}

const NBA_PROFILE: StatProfile = {
  tracked: true,
  tiles: ["points", "rebounds", "assists", "minutes"],
  rows: [FPTS, "minutes", "points", "rebounds", "assists", "steals", "blocks", "turnovers"],
  defaultStat: "points",
};

const NFL_PROFILES: Record<string, StatProfile> = {
  QB: {
    tracked: true,
    tiles: ["passing_yards", "passing_touchdowns", "interceptions", "rushing_yards"],
    rows: [
      FPTS,
      "passing_completions",
      "passing_attempts",
      "passing_yards",
      "passing_touchdowns",
      "interceptions",
      "rushing_yards",
    ],
    defaultStat: "passing_yards",
  },
  RB: {
    tracked: true,
    tiles: ["rushing_attempts", "rushing_yards", "receptions", "rushing_touchdowns"],
    rows: [
      FPTS,
      "rushing_attempts",
      "rushing_yards",
      "rushing_touchdowns",
      "receptions",
      "receiving_yards",
    ],
    defaultStat: "rushing_yards",
  },
  RECEIVER: {
    tracked: true,
    tiles: ["receptions", "receiving_targets", "receiving_yards", "receiving_touchdowns"],
    rows: [
      FPTS,
      "receiving_targets",
      "receptions",
      "receiving_yards",
      "receiving_touchdowns",
      "rushing_yards",
    ],
    defaultStat: "receiving_yards",
  },
  // Kickers and punters: no kicking stats are stored yet, so there is nothing to chart.
  KICKER: {
    tracked: false,
    tiles: [],
    rows: [FPTS],
    defaultStat: FPTS,
  },
  // Linemen and defenders: the stats we store don't describe them well.
  OTHER: {
    tracked: true,
    tiles: ["passing_yards", "rushing_yards", "receptions", "receiving_yards"],
    rows: [FPTS, "passing_yards", "rushing_yards", "receptions", "receiving_yards"],
    defaultStat: "receiving_yards",
  },
};

export function profileFor(sport: Sport, position: string | null): StatProfile {
  if (sport === "NBA") return NBA_PROFILE;
  if (position === "QB") return NFL_PROFILES.QB;
  if (position === "RB" || position === "FB") return NFL_PROFILES.RB;
  if (position === "WR" || position === "TE") return NFL_PROFILES.RECEIVER;
  if (isSpecialTeamer(position)) return NFL_PROFILES.KICKER;
  return NFL_PROFILES.OTHER;
}

/** One value for a stat in a game; fantasy points are derived from the stat line. */
export function statValue(
  entry: PlayerGameStatsEntry,
  key: string,
  sport: Sport,
): number {
  if (key === FPTS) {
    return fantasyPoints(entry.stats, DEFAULT_SCORING[sport].weights);
  }
  return entry.stats[key] ?? 0;
}

export function average(values: number[]): number {
  return values.length === 0
    ? 0
    : values.reduce((sum, value) => sum + value, 0) / values.length;
}

/** Whole numbers stay whole; everything else gets one decimal. */
export function formatStat(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

export interface LogColumn {
  key: string;
  group?: string;
}

export const NBA_LOG_COLUMNS: LogColumn[] = [
  "minutes",
  "points",
  "rebounds",
  "assists",
  "steals",
  "blocks",
  "turnovers",
  "field_goal_attempts",
  "three_point_attempts",
  FPTS,
].map((key) => ({ key }));

export const NFL_LOG_COLUMNS: LogColumn[] = [
  { key: "passing_completions", group: "Passing" },
  { key: "passing_attempts", group: "Passing" },
  { key: "passing_yards", group: "Passing" },
  { key: "passing_touchdowns", group: "Passing" },
  { key: "interceptions", group: "Passing" },
  { key: "rushing_attempts", group: "Rushing" },
  { key: "rushing_yards", group: "Rushing" },
  { key: "rushing_touchdowns", group: "Rushing" },
  { key: "receptions", group: "Receiving" },
  { key: "receiving_targets", group: "Receiving" },
  { key: "receiving_yards", group: "Receiving" },
  { key: "receiving_touchdowns", group: "Receiving" },
  { key: "fumbles_lost", group: "Misc" },
  { key: FPTS, group: "Misc" },
];
