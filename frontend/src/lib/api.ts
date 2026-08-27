/**
 * Small typed API client for talking to the FastAPI backend.
 *
 * Every backend call the frontend makes should go through a function
 * here, not through ad-hoc fetch() calls scattered across components.
 * This is the seed of the client layer that will grow as the API grows.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  environment: string;
}

export async function getHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_URL}/api/v1/health`, {
    // Always hit the backend fresh for this dev-stack status check.
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`Backend health check failed: ${res.status}`);
  }

  return res.json();
}
