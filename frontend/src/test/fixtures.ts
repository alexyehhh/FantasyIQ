import type {
  DefenseDetail,
  DefenseListItem,
  PlayerDetail,
  PlayerListItem,
  PlayerGameStatsEntry,
  PlayerSummary,
  ProjectionEntry,
  ScheduleEntry,
  ScoringConfig,
  SeasonSummary,
  TeamSummary,
} from "@/lib/api";

export function makeTeam(overrides: Partial<TeamSummary> = {}): TeamSummary {
  return {
    id: 1,
    name: "Golden State Warriors",
    abbreviation: "GSW",
    logo_url: null,
    primary_color: "#1d428a",
    bye_week: null,
    ...overrides,
  };
}

export function makePlayerSummary(
  overrides: Partial<PlayerSummary> = {},
): PlayerSummary {
  return {
    id: 1,
    name: "Steph Curry",
    sport: "NBA",
    team_id: 1,
    team: makeTeam(),
    position: "G",
    jersey_number: 30,
    active: true,
    headshot_url: null,
    injury_status: null,
    ...overrides,
  };
}

export function makePlayerListItem(
  overrides: Partial<PlayerListItem> = {},
): PlayerListItem {
  return { ...makePlayerSummary(), fantasy_points: 42.5, ...overrides };
}

export function makePlayerDetail(
  overrides: Partial<PlayerDetail> = {},
): PlayerDetail {
  return {
    ...makePlayerSummary(),
    external_id: "espn-1",
    height_inches: 74,
    weight_lbs: 185,
    birth_date: "1988-03-14",
    college: "Davidson",
    experience_years: 16,
    injury: null,
    next_game: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeEntry(
  overrides: Partial<PlayerGameStatsEntry> = {},
): PlayerGameStatsEntry {
  return {
    game_id: 1,
    game_date: "2026-01-05T18:00:00Z",
    status: "final",
    week: null,
    stats: { points: 30 },
    fantasy_points: 30,
    opponent: null,
    is_home: null,
    team_score: null,
    opponent_score: null,
    result: null,
    ...overrides,
  };
}

/** `count` NBA games, most recent first, scoring 20, 21, 22, ... */
export function makeNbaGames(count: number): PlayerGameStatsEntry[] {
  return Array.from({ length: count }, (_, index) =>
    makeEntry({
      game_id: count - index,
      game_date: new Date(Date.UTC(2026, 0, 30 - index, 18)).toISOString(),
      stats: {
        minutes: 30,
        points: 20 + (count - index),
        rebounds: 5,
        assists: 6,
        steals: 1,
        blocks: 0,
        turnovers: 2,
        field_goal_attempts: 15,
        three_point_attempts: 7,
      },
    }),
  );
}

export function makeScheduleEntry(
  overrides: Partial<ScheduleEntry> = {},
): ScheduleEntry {
  return {
    game_id: 100,
    game_date: "2999-01-05T18:00:00Z",
    status: "scheduled",
    week: null,
    is_home: true,
    opponent: makeTeam({ id: 2, name: "Los Angeles Lakers", abbreviation: "LAL" }),
    team_score: null,
    opponent_score: null,
    result: null,
    ...overrides,
  };
}

/** `count` upcoming games on consecutive days from March, soonest first, with ids from 1000. */
export function makeUpcoming(count: number): ScheduleEntry[] {
  return Array.from({ length: count }, (_, index) =>
    makeScheduleEntry({
      game_id: 1000 + index,
      game_date: new Date(Date.UTC(2999, 2, 1 + index, 18)).toISOString(),
    }),
  );
}

/** The schedule rows for games already played, as the API lists them for the current season. */
export function scheduleFromGames(entries: PlayerGameStatsEntry[]): ScheduleEntry[] {
  return entries.map((entry) =>
    makeScheduleEntry({
      game_id: entry.game_id,
      game_date: entry.game_date,
      status: "final",
      week: entry.week,
      is_home: entry.is_home,
      opponent: entry.opponent,
      team_score: entry.team_score,
      opponent_score: entry.opponent_score,
      result: entry.result,
    }),
  );
}

/** A small NFL scoring config with distance-bracketed kickers and a bracketed defense. */
export function makeScoringConfig(overrides: Partial<ScoringConfig> = {}): ScoringConfig {
  return {
    name: "Test league",
    sport: "NFL",
    player_weights: { passing_yards: 0.04, receptions: 1, extra_points_made: 1 },
    field_goal_made: [
      { min: 0, max: 39, points: 3 },
      { min: 40, max: null, points: 5 },
    ],
    field_goal_missed: [{ min: 0, max: null, points: -1 }],
    defense_weights: { sacks: 1 },
    points_allowed: [
      { min: 0, max: 0, points: 10 },
      { min: 1, max: null, points: 0 },
    ],
    ...overrides,
  };
}

const BENGALS = { id: 7, name: "Cincinnati Bengals", abbreviation: "CIN", bye_week: 6 };

export function makeDefenseListItem(overrides: Partial<DefenseListItem> = {}): DefenseListItem {
  return { ...makeTeam(BENGALS), fantasy_points: 34, ...overrides };
}

export function makeDefenseDetail(overrides: Partial<DefenseDetail> = {}): DefenseDetail {
  return { ...makeTeam(BENGALS), next_game: null, ...overrides };
}

/** One defense game line under the default scoring (sacks 1, INT 2, ..., points allowed brackets). */
export function makeDefenseEntry(
  overrides: Partial<PlayerGameStatsEntry> = {},
): PlayerGameStatsEntry {
  return makeEntry({
    week: 1,
    stats: {
      sacks: 4,
      interceptions: 1,
      fumble_recoveries: 0,
      defensive_touchdowns: 0,
      return_touchdowns: 0,
      safeties: 0,
      blocked_kicks: 0,
      fourth_down_stops: 2,
      points_allowed: 13,
      yards_allowed: 301,
    },
    fantasy_points: 12,
    ...overrides,
  });
}

/** A QB's season: 583 passing yards ranked 3rd of 32 QBs, tied on 2 TDs, first in fantasy points. */
export function makeSeasonSummary(overrides: Partial<SeasonSummary> = {}): SeasonSummary {
  return {
    season: "2026",
    games: 2,
    position_group: "QB",
    pool_size: 32,
    stats: {
      fantasy_points: { total: 41.5, rank: 1, tied: false },
      passing_yards: { total: 583, rank: 3, tied: false },
      passing_touchdowns: { total: 2, rank: 9, tied: true },
      interceptions: { total: 1, rank: 12, tied: false },
      rushing_yards: { total: 40, rank: 7, tied: false },
    },
    ...overrides,
  };
}

export function makeProjectionEntry(
  overrides: Partial<ProjectionEntry> = {},
): ProjectionEntry {
  return {
    kind: "player",
    id: 1,
    name: "Jahmyr Gibbs",
    position: "RB",
    team: makeTeam({ id: 8, name: "Detroit Lions", abbreviation: "DET" }),
    headshot_url: null,
    source: "sleeper",
    status: "ok",
    fantasy_points: 20,
    low: 12,
    high: 28,
    std: 8,
    spread_basis: "position",
    chance_best: null,
    game: {
      game_id: 11,
      start_time: "2026-09-27T17:00:00Z",
      status: "scheduled",
      week: 3,
      is_home: true,
      opponent: makeTeam({ id: 9, name: "New York Jets", abbreviation: "NYJ" }),
    },
    stats: {},
    games_sampled: 2,
    injury_status: null,
    approximate: false,
    unprojected_stats: [],
    notes: [],
    ...overrides,
  };
}
