import Link from "next/link";
import { getHealth } from "@/lib/api";

export default async function HomePage() {
  let status: string;
  let environment: string;
  let error: string | null = null;

  try {
    const health = await getHealth();
    status = health.status;
    environment = health.environment;
  } catch {
    status = "unreachable";
    environment = "unknown";
    error = "Could not reach the backend. Is it running?";
  }

  const isOk = status === "ok";

  return (
    <main className="flex min-h-[calc(100vh-56px)] flex-col items-center justify-center gap-4 p-8">
      <h1 className="font-display text-5xl font-bold uppercase tracking-wide">FantasyIQ</h1>
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-3 w-3 rounded-full ${isOk ? "bg-good" : "bg-bad"}`}
        />
        <span>
          Backend status: <strong>{status}</strong> ({environment})
        </span>
      </div>
      {error && <p className="text-sm text-bad">{error}</p>}
      <Link href="/players" className="font-semibold text-accent hover:underline">
        Browse players &rarr;
      </Link>
    </main>
  );
}
