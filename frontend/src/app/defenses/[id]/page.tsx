import Link from "next/link";
import { notFound } from "next/navigation";
import DefenseHero from "@/components/DefenseHero";
import PlayerStats from "@/components/PlayerStats";
import {
  getDefense,
  getDefenseSchedule,
  getDefenseSeason,
  getDefenseStats,
  getScoringPreset,
} from "@/lib/api";

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
