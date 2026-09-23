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
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-24">
      <h1 className="text-3xl font-bold">FantasyIQ</h1>
      <div className="flex items-center gap-2">
        <span
          className={`inline-block h-3 w-3 rounded-full ${
            isOk ? "bg-green-500" : "bg-red-500"
          }`}
        />
        <span>
          Backend status: <strong>{status}</strong> ({environment})
        </span>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <Link href="/players" className="text-blue-600 hover:underline">
        Browse players &rarr;
      </Link>
    </main>
  );
}
