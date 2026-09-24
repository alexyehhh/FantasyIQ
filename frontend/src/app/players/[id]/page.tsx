import Link from "next/link";
import { notFound } from "next/navigation";
import InjuryNote from "@/components/InjuryNote";
import PlayerHero from "@/components/PlayerHero";
import PlayerStats from "@/components/PlayerStats";
import { getPlayer, getPlayerSchedule, getPlayerStats } from "@/lib/api";

// The API's maximum page: enough for a whole season of results.
const GAME_LOG_LIMIT = 200;

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

  const [stats, schedule] = await Promise.all([
    getPlayerStats(playerId, GAME_LOG_LIMIT),
    getPlayerSchedule(playerId),
  ]);

  return (
    <main className="mx-auto max-w-[1120px] px-4 pb-14 pt-6">
      <Link
        href="/players"
        className="mb-3.5 inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink-2 hover:text-accent"
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="m15 6-6 6 6 6" />
        </svg>
        Back to players
      </Link>

      <PlayerHero player={player} entries={stats ?? []} />
      {player.injury && <InjuryNote injury={player.injury} />}
      <PlayerStats
        key={player.id}
        sport={player.sport}
        position={player.position}
        entries={stats ?? []}
        schedule={schedule ?? []}
        byeWeek={player.team?.bye_week ?? null}
      />
    </main>
  );
}
