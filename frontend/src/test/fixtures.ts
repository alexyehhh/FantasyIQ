import type {
  PlayerDetail,
  PlayerListItem,
  PlayerGameStatsEntry,
  PlayerSummary,
  ScheduleEntry,
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
    week: null,
    stats: { points: 30 },
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
