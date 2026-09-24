/**
 * Everything the player pages know about how to present a stat line: labels,
 * which stats matter for which position, and the game-log columns. The stats
 * dict the API returns is sport-shaped (see app/schemas/players.py), so this
 * is the one place that maps those raw keys to what a fan expects to read.
 */

import type { Kick, PlayerGameStatsEntry, Sport } from "./api";

export const FPTS = "fpts";
/** A game-log column that lists a kicker's field goal attempts instead of one number. */
export const KICKS = "kicks";

export const STAT_LABELS: Record<string, { name: string; abbr: string }> = {
  [FPTS]: { name: "Fantasy pts", abbr: "FPTS" },
  minutes: { name: "Minutes", abbr: "MIN" },
  points: { name: "Points", abbr: "PTS" },
  rebounds: { name: "Rebounds", abbr: "REB" },
  assists: { name: "Assists", abbr: "AST" },
  steals: { name: "Steals", abbr: "STL" },
  blocks: { name: "Blocks", abbr: "BLK" },
  turnovers: { name: "Turnovers", abbr: "TO" },
  field_goals_made: { name: "Field goals made", abbr: "FGM" },
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
  kick_return_touchdowns: { name: "Kick return TDs", abbr: "KR TD" },
  punt_return_touchdowns: { name: "Punt return TDs", abbr: "PR TD" },
  extra_points_made: { name: "Extra points made", abbr: "XPM" },
  extra_point_attempts: { name: "Extra point attempts", abbr: "XPA" },
  [KICKS]: { name: "Field goals", abbr: "FG yards" },
  // Team defense (D/ST)
  sacks: { name: "Sacks", abbr: "SCK" },
  fumble_recoveries: { name: "Fumble recoveries", abbr: "FR" },
  safeties: { name: "Safeties", abbr: "SAF" },
  blocked_kicks: { name: "Blocked kicks", abbr: "BLK" },
  defensive_touchdowns: { name: "Defensive TDs", abbr: "DTD" },
  return_touchdowns: { name: "Return TDs", abbr: "RTD" },
  fourth_down_stops: { name: "4th down stops", abbr: "4DS" },
  points_allowed: { name: "Points allowed", abbr: "PA" },
  yards_allowed: { name: "Yards allowed", abbr: "YA" },
};

/** Stats where a lower number is better, so a rising trend is bad news. */
export const NEGATIVE_STATS = new Set(["turnovers", "interceptions", "fumbles_lost"]);

/** A team defense wants fewer points and yards allowed; its interceptions are good news. */
export const DEFENSE_NEGATIVE_STATS = new Set(["points_allowed", "yards_allowed"]);

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

const KICKER_LOG_COLUMNS: LogColumn[] = [
  { key: "field_goals_made", group: "Field goals" },
  { key: "field_goal_attempts", group: "Field goals" },
  { key: KICKS, group: "Field goals" },
  { key: "extra_points_made", group: "Extra points" },
  { key: "extra_point_attempts", group: "Extra points" },
  { key: FPTS, group: "Misc" },
];

const DEFENSE_LOG_COLUMNS: LogColumn[] = [
  { key: "sacks", group: "Takeaways" },
  { key: "interceptions", group: "Takeaways" },
  { key: "fumble_recoveries", group: "Takeaways" },
  { key: "defensive_touchdowns", group: "Scores" },
  { key: "return_touchdowns", group: "Scores" },
  { key: "safeties", group: "Scores" },
  { key: "blocked_kicks", group: "Scores" },
  { key: "fourth_down_stops", group: "Allowed" },
  { key: "points_allowed", group: "Allowed" },
  { key: "yards_allowed", group: "Allowed" },
  { key: FPTS, group: "Misc" },
];

export interface StatProfile {
  /** False when the stat lines we store say nothing about this position. */
  tracked: boolean;
  /** The four stats shown beside fantasy points in the header. */
  tiles: string[];
  /** Rows of the averages table and the stat chips above the chart (fantasy points first). */
  rows: string[];
  defaultStat: string;
  /** The game log's columns. */
  logColumns: LogColumn[];
  /** Stats where a rising trend is bad news. */
  negativeStats: ReadonlySet<string>;
  /** Which of the backend's scoring config applies to this kind of stat line. */
  scoringKind: "player" | "kicker" | "defense";
  /** What the untracked message calls the missing stats. */
  untrackedLabel?: string;
}

const NBA_PROFILE: StatProfile = {
  tracked: true,
  tiles: ["points", "rebounds", "assists", "minutes"],
  rows: [FPTS, "minutes", "points", "rebounds", "assists", "steals", "blocks", "turnovers"],
  defaultStat: "points",
  logColumns: NBA_LOG_COLUMNS,
  negativeStats: NEGATIVE_STATS,
  scoringKind: "player",
};

const NFL_PLAYER: Pick<StatProfile, "tracked" | "logColumns" | "negativeStats" | "scoringKind"> = {
  tracked: true,
  logColumns: NFL_LOG_COLUMNS,
  negativeStats: NEGATIVE_STATS,
  scoringKind: "player",
};

const NFL_PROFILES: Record<string, StatProfile> = {
  QB: {
    ...NFL_PLAYER,
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
    ...NFL_PLAYER,
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
    ...NFL_PLAYER,
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
  KICKER: {
    tracked: true,
    tiles: ["field_goals_made", "field_goal_attempts", "extra_points_made", "extra_point_attempts"],
    rows: [
      FPTS,
      "field_goals_made",
      "field_goal_attempts",
      "extra_points_made",
      "extra_point_attempts",
    ],
    defaultStat: FPTS,
    logColumns: KICKER_LOG_COLUMNS,
    negativeStats: NEGATIVE_STATS,
    scoringKind: "kicker",
  },
  // Punters: no punting stats are stored yet, so there is nothing to chart.
  PUNTER: {
    tracked: false,
    tiles: [],
    rows: [FPTS],
    defaultStat: FPTS,
    logColumns: [],
    negativeStats: NEGATIVE_STATS,
    scoringKind: "player",
    untrackedLabel: "Punting",
  },
  // Linemen and defenders: the stats we store don't describe them well.
  OTHER: {
    ...NFL_PLAYER,
    tiles: ["passing_yards", "rushing_yards", "receptions", "receiving_yards"],
    rows: [FPTS, "passing_yards", "rushing_yards", "receptions", "receiving_yards"],
    defaultStat: "receiving_yards",
  },
  // A team defense (D/ST), addressed on the defense pages as position "DEF".
  DEF: {
    tracked: true,
    tiles: ["sacks", "interceptions", "points_allowed", "yards_allowed"],
    rows: [
      FPTS,
      "sacks",
      "interceptions",
      "fumble_recoveries",
      "defensive_touchdowns",
      "safeties",
      "blocked_kicks",
      "fourth_down_stops",
      "points_allowed",
      "yards_allowed",
    ],
    defaultStat: FPTS,
    logColumns: DEFENSE_LOG_COLUMNS,
    negativeStats: DEFENSE_NEGATIVE_STATS,
    scoringKind: "defense",
  },
};

export function profileFor(sport: Sport, position: string | null): StatProfile {
  if (sport === "NBA") return NBA_PROFILE;
  if (position === "QB") return NFL_PROFILES.QB;
  if (position === "RB" || position === "FB") return NFL_PROFILES.RB;
  if (position === "WR" || position === "TE") return NFL_PROFILES.RECEIVER;
  if (position === "PK") return NFL_PROFILES.KICKER;
  if (position === "P") return NFL_PROFILES.PUNTER;
  if (position === "DEF") return NFL_PROFILES.DEF;
  return NFL_PROFILES.OTHER;
}

/** One value for a stat in a game; fantasy points are the backend's, under its default scoring. */
export function statValue(entry: PlayerGameStatsEntry, key: string): number {
  if (key === FPTS) return entry.fantasy_points;
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

/** A kicker's attempts as "24, 52, 43 (miss)": distances in yards, misses and blocks marked. */
export function formatKicks(kicks: Kick[] | undefined): string {
  if (!kicks || kicks.length === 0) return "—";
  return kicks
    .map((kick) =>
      kick.result === "made"
        ? String(kick.distance)
        : `${kick.distance} (${kick.result === "missed" ? "miss" : "blocked"})`,
    )
    .join(", ");
}
