import Link from "next/link";
import { notFound } from "next/navigation";
import LiveRefresh from "@/components/LiveRefresh";
import DefenseHero from "@/components/DefenseHero";
import PlayerStats from "@/components/PlayerStats";
import {
  getDefense,
  getDefenseSchedule,
  getDefenseSeason,
  getDefenseStats,
  getScoringPreset,
} from "@/lib/api";
import { hasLiveGame } from "@/lib/liveGames";

// The API's maximum page: enough for a whole season of results.
const GAME_LOG_LIMIT = 200;

export default async function DefenseDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const teamId = Number(id);
  if (!Number.isInteger(teamId)) {
    notFound();
  }

  const defense = await getDefense(teamId);
  if (!defense) {
    notFound();
  }

  const [stats, schedule, scoring, season] = await Promise.all([
    getDefenseStats(teamId, GAME_LOG_LIMIT, "current"),
    getDefenseSchedule(teamId),
    getScoringPreset("NFL"),
    getDefenseSeason(teamId),
  ]);

  // While a game is on (or about to start), keep the page's stats current without a reload.
  const live = hasLiveGame(schedule ?? [], Date.now());

  return (
    <main className="mx-auto max-w-[1120px] px-4 pb-14 pt-6">
      <div className="mb-3.5 flex items-center justify-between gap-3">
        <Link
          href="/players"
          className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-ink-2 hover:text-accent"
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
        {live && <LiveRefresh />}
      </div>

      <DefenseHero defense={defense} entries={stats ?? []} season={season} />
      <PlayerStats
        key={defense.id}
        sport="NFL"
        position="DEF"
        entries={stats ?? []}
        schedule={schedule ?? []}
        byeWeek={defense.bye_week}
        scoring={scoring}
      />
    </main>
  );
}
