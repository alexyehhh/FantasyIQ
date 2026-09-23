import Link from "next/link";
import { notFound } from "next/navigation";
import StatChart from "@/components/StatChart";
import { getPlayer, getPlayerStats } from "@/lib/api";

export default async function PlayerDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const playerId = Number(id);
  if (!Number.isInteger(playerId)) {
    notFound();
  }

  const player = await getPlayer(playerId);
  if (!player) {
    notFound();
  }

  const stats = (await getPlayerStats(playerId, 20)) ?? [];

  return (
    <main className="mx-auto max-w-3xl p-8">
      <Link href="/players" className="text-sm text-blue-600 hover:underline">
        &larr; Back to players
      </Link>

      <h1 className="mt-2 text-2xl font-bold">{player.name}</h1>
      <p className="text-gray-500">
        {player.sport}
        {player.position ? ` · ${player.position}` : ""}
        {player.jersey_number ? ` · #${player.jersey_number}` : ""}
      </p>

      <section className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">Recent games</h2>
        <StatChart sport={player.sport} entries={stats} />
      </section>
    </main>
  );
}
