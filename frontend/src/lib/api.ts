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

export interface PlayerSummary {
  id: number;
  name: string;
  sport: Sport;
  team_id: number | null;
  position: string | null;
  jersey_number: number | null;
  active: boolean;
}

export interface PlayerDetail extends PlayerSummary {
  external_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlayerListResponse {
  items: PlayerSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface PlayerGameStatsEntry {
  game_id: number;
  game_date: string;
  stats: Record<string, number>;
}

export interface ListPlayersParams {
  sport?: Sport;
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
  if (params.teamId !== undefined) query.set("team_id", String(params.teamId));
  if (params.search) query.set("search", params.search);
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
