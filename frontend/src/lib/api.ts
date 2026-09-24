/**
 * Small typed API client for talking to the FastAPI backend.
 *
 * Every backend call the frontend makes should go through a function
 * here, not through ad-hoc fetch() calls scattered across components.
 * This is the seed of the client layer that will grow as the API grows.
 */

const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Server-rendered pages (RSC) run inside the frontend's own container, where
 * "localhost" points at that container, not the backend one — INTERNAL_API_URL
 * (the backend's Docker Compose service name) is used there instead. The
 * browser can't resolve that service name, so client components always use
 * the publicly reachable NEXT_PUBLIC_API_URL.
 */
function apiUrl(): string {
  if (typeof window === "undefined") {
    return process.env.INTERNAL_API_URL ?? PUBLIC_API_URL;
  }
  return PUBLIC_API_URL;
}

export interface HealthResponse {
  status: string;
  environment: string;
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch(`${apiUrl()}/api/v1/health`, {
    // Always hit the backend fresh for this dev-stack status check.
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend health check failed: ${res.status}`);
  }

  return res.json();
}

export type Sport = "NBA" | "NFL";

export interface TeamSummary {
  id: number;
  name: string;
  abbreviation: string;
  logo_url: string | null;
  primary_color: string | null;
  // NFL only: this season's bye week.
  bye_week: number | null;
}

export interface PlayerSummary {
  id: number;
  name: string;
  sport: Sport;
  team_id: number | null;
  team: TeamSummary | null;
  position: string | null;
  jersey_number: number | null;
  active: boolean;
  headshot_url: string | null;
  injury_status: string | null;
}

/** A player as listed, with fantasy points (default scoring) for the latest season with stats. */
export interface PlayerListItem extends PlayerSummary {
  fantasy_points: number | null;
}

export interface InjuryReport {
  status: string;
  type: string | null;
  note: string | null;
  updated_at: string | null;
}

export interface NextGame {
  game_id: number;
  start_time: string;
  status: string;
  is_home: boolean;
  opponent: TeamSummary;
}

export interface PlayerDetail extends PlayerSummary {
  external_id: string | null;
  height_inches: number | null;
  weight_lbs: number | null;
  birth_date: string | null;
  college: string | null;
  experience_years: number | null;
  injury: InjuryReport | null;
  next_game: NextGame | null;
  created_at: string;
  updated_at: string;
}

export interface PlayerListResponse {
  items: PlayerListItem[];
  total: number;
  limit: number;
  offset: number;
}

/** One field goal attempt: its distance in yards and how it ended. */
export interface Kick {
  distance: number;
  result: "made" | "missed" | "blocked";
}

export interface PlayerGameStatsEntry {
  game_id: number;
  game_date: string;
  week: number | null;
  stats: Record<string, number>;
  /** The game's fantasy points under the scoring the backend used (the sport's default). */
  fantasy_points: number;
  /** An NFL kicker's field goal attempts in order; absent for everyone else. */
  kicks?: Kick[];
  // Relative to the player's current team; null when the game can't be tied to it.
  opponent: TeamSummary | null;
  is_home: boolean | null;
  team_score: number | null;
  opponent_score: number | null;
  result: "W" | "L" | "T" | null;
}

/** One game on the player's team's schedule this season, played or not. */
export interface ScheduleEntry {
  game_id: number;
  game_date: string;
  status: "scheduled" | "in_progress" | "final";
  week: number | null;
  is_home: boolean | null;
  opponent: TeamSummary | null;
  team_score: number | null;
  opponent_score: number | null;
  result: "W" | "L" | "T" | null;
}

export interface ListPlayersParams {
  sport?: Sport;
  /** Match any of these position codes, e.g. ["RB", "WR", "TE"]. */
  positions?: string[];
  /** "fantasy_points" ranks most first and needs `sport`. Defaults to name. */
  sort?: "name" | "fantasy_points";
  teamId?: number;
  search?: string;
  limit?: number;
  offset?: number;
}

export async function listPlayers(
  params: ListPlayersParams = {},
): Promise<PlayerListResponse> {
  const query = new URLSearchParams();
  if (params.sport) query.set("sport", params.sport);
  for (const position of params.positions ?? []) query.append("position", position);
  if (params.teamId !== undefined) query.set("team_id", String(params.teamId));
  if (params.search) query.set("search", params.search);
  if (params.sort) query.set("sort", params.sort);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));

  const res = await fetch(`${apiUrl()}/api/v1/players?${query.toString()}`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Failed to list players: ${res.status}`);
  }

  return res.json();
}

export async function getPlayer(id: number): Promise<PlayerDetail | null> {
  const res = await fetch(`${apiUrl()}/api/v1/players/${id}`, {
    cache: "no-store",
  });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch player ${id}: ${res.status}`);
  }

  return res.json();
}

export async function getPlayerStats(
  id: number,
  limit?: number,
): Promise<PlayerGameStatsEntry[] | null> {
  const query = limit !== undefined ? `?limit=${limit}` : "";
  const res = await fetch(`${apiUrl()}/api/v1/players/${id}/stats${query}`, {
    cache: "no-store",
  });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch stats for player ${id}: ${res.status}`);
  }

  return res.json();
}

export async function getPlayerSchedule(id: number): Promise<ScheduleEntry[] | null> {
  const res = await fetch(`${apiUrl()}/api/v1/players/${id}/schedule`, {
    cache: "no-store",
  });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch schedule for player ${id}: ${res.status}`);
  }

  return res.json();
}

/** An inclusive range of whole numbers worth `points`; a null end is open (0-19, 35+). */
export interface Bracket {
  min: number | null;
  max: number | null;
  points: number;
}

/** A league's scoring, as the backend defines it (app/services/scoring.py). */
export interface ScoringConfig {
  name: string;
  sport: Sport;
  player_weights: Record<string, number>;
  field_goal_made: Bracket[];
  field_goal_missed: Bracket[];
  defense_weights: Record<string, number>;
  points_allowed: Bracket[];
}

/** The FantasyIQ default scoring for a sport, or null if the backend can't be asked. */
export async function getScoringPreset(sport: Sport): Promise<ScoringConfig | null> {
  try {
    const res = await fetch(`${apiUrl()}/api/v1/scoring/presets/${sport}`, {
      cache: "no-store",
    });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/** A team defense (D/ST) as listed, with fantasy points for the latest season with stats. */
export interface DefenseListItem extends TeamSummary {
  fantasy_points: number | null;
}

export interface DefenseListResponse {
  items: DefenseListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface DefenseDetail extends TeamSummary {
  next_game: NextGame | null;
}

/** A defense's game line has the same shape as a player's (no `kicks`); `stats` are sacks, etc. */
export type DefenseGameStatsEntry = PlayerGameStatsEntry;

export interface ListDefensesParams {
  search?: string;
  /** "fantasy_points" ranks most first. Defaults to name. */
  sort?: "name" | "fantasy_points";
  limit?: number;
  offset?: number;
}

export async function listDefenses(
  params: ListDefensesParams = {},
): Promise<DefenseListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set("search", params.search);
  if (params.sort) query.set("sort", params.sort);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));

  const res = await fetch(`${apiUrl()}/api/v1/defenses?${query.toString()}`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Failed to list defenses: ${res.status}`);
  }

  return res.json();
}

export async function getDefense(id: number): Promise<DefenseDetail | null> {
  const res = await fetch(`${apiUrl()}/api/v1/defenses/${id}`, { cache: "no-store" });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch defense ${id}: ${res.status}`);
  }

  return res.json();
}

export async function getDefenseStats(
  id: number,
  limit?: number,
): Promise<DefenseGameStatsEntry[] | null> {
  const query = limit !== undefined ? `?limit=${limit}` : "";
  const res = await fetch(`${apiUrl()}/api/v1/defenses/${id}/stats${query}`, {
    cache: "no-store",
  });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch stats for defense ${id}: ${res.status}`);
  }

  return res.json();
}

export async function getDefenseSchedule(id: number): Promise<ScheduleEntry[] | null> {
  const res = await fetch(`${apiUrl()}/api/v1/defenses/${id}/schedule`, {
    cache: "no-store",
  });

  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`Failed to fetch schedule for defense ${id}: ${res.status}`);
  }

  return res.json();
}

/** A season total and its rank (1 = best) among the same position; `tied` if others share it. */
export interface RankedStat {
  total: number;
  rank: number;
  tied: boolean;
}

/**
 * A player's or defense's totals for the latest season with stats, each ranked among the
 * `pool_size` players in `position_group`. `stats` has every stat plus `fantasy_points`.
 */
export interface SeasonSummary {
  season: string;
  games: number;
  position_group: string;
  pool_size: number;
  stats: Record<string, RankedStat>;
}

async function fetchSeason(path: string): Promise<SeasonSummary | null> {
  try {
    const res = await fetch(`${apiUrl()}${path}`, { cache: "no-store" });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/** A player's season totals and ranks, or null before they've played (or if it can't be fetched). */
export function getPlayerSeason(id: number): Promise<SeasonSummary | null> {
  return fetchSeason(`/api/v1/players/${id}/season`);
}

/** A defense's season totals and ranks among the defenses, or null if there are none. */
export function getDefenseSeason(id: number): Promise<SeasonSummary | null> {
  return fetchSeason(`/api/v1/defenses/${id}/season`);
}
