import type { DefenseDetail, DefenseGameStatsEntry, SeasonSummary } from "@/lib/api";
import { FPTS, profileFor } from "@/lib/stats";
import { NextGameBlock, Tiles } from "./PlayerHero";
import TeamLogo from "./TeamLogo";

interface DefenseHeroProps {
  defense: DefenseDetail;
  /** Most recent game first, as the API returns them. */
  entries: DefenseGameStatsEntry[];
  /** Season totals with ranks among the defenses; without it the tiles show last-10 averages. */
  season?: SeasonSummary | null;
}

/** The top of a defense page: the team, its bye week and next game, and last-10 stat tiles. */
export default function DefenseHero({ defense, entries, season = null }: DefenseHeroProps) {
  const profile = profileFor("NFL", "DEF");
  const details = [
    "D/ST",
    defense.bye_week !== null ? `Bye week ${defense.bye_week}` : null,
  ].filter((part): part is string => part !== null);

  return (
    <section
      aria-label="Defense summary"
      className="overflow-hidden rounded-2xl border border-line bg-surface shadow-panel"
    >
      <div
        className="flex flex-col gap-5 border-b border-line p-5 sm:p-7 md:flex-row md:items-center"
        style={{
          background: `color-mix(in srgb, ${defense.primary_color ?? "var(--ink-3)"} 13%, var(--surface))`,
        }}
      >
        <div className="flex min-w-0 flex-1 items-center gap-5 sm:gap-[22px]">
          <TeamLogo team={defense} className="h-[88px] w-[88px]" />
          <div className="min-w-0">
            <div className="text-[13px] font-semibold text-ink-2">
              {defense.abbreviation} · NFL
            </div>
            <h1 className="my-1 font-display text-[42px] font-bold uppercase leading-[0.95] tracking-[0.015em] sm:text-[54px]">
              {defense.name}
            </h1>
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-semibold text-ink-2">
              {details.map((part, index) => (
                <span key={part} className="flex items-center gap-2.5">
                  {index > 0 && (
                    <span aria-hidden="true" className="h-1 w-1 rounded-full bg-ink-3" />
                  )}
                  {part}
                </span>
              ))}
            </div>
          </div>
        </div>
        <NextGameBlock nextGame={defense.next_game} hasTeam />
      </div>

      <Tiles
        sport="NFL"
        entries={entries}
        tiles={[FPTS, ...profile.tiles]}
        negativeStats={profile.negativeStats}
        season={season}
      />
    </section>
  );
}
