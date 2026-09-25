import type {
  NextGame,
  PlayerDetail,
  PlayerGameStatsEntry,
  RankedStat,
  SeasonSummary,
  Sport,
} from "@/lib/api";
import { formatGameDateTime } from "@/lib/format";
import { displayPosition } from "@/lib/positions";
import {
  FPTS,
  STAT_LABELS,
  formatStat,
  profileFor,
} from "@/lib/stats";
import PlayerAvatar from "./PlayerAvatar";
import StatusPill from "./StatusPill";
import TeamLogo from "./TeamLogo";

interface PlayerHeroProps {
  player: PlayerDetail;
  /** Most recent game first, as the API returns them. */
  entries: PlayerGameStatsEntry[];
  /** Season totals with ranks; without it the tiles show dashes. */
  season?: SeasonSummary | null;
}

export default function PlayerHero({ player, entries, season = null }: PlayerHeroProps) {
  const team = player.team;
  const profile = profileFor(player.sport, player.position);
  const byeWeek = team?.bye_week ?? null;
  const details = [
    displayPosition(player.position),
    player.jersey_number !== null ? `#${player.jersey_number}` : null,
    byeWeek !== null ? `Bye week ${byeWeek}` : null,
  ].filter((part): part is string => part !== null);

  return (
    <section
      aria-label="Player summary"
      className="overflow-hidden rounded-2xl border border-line bg-surface shadow-panel"
    >
      <div
        className="flex flex-col gap-5 border-b border-line p-5 sm:p-7 md:flex-row md:items-center"
        style={{
          background: `color-mix(in srgb, ${team?.primary_color ?? "var(--ink-3)"} 13%, var(--surface))`,
        }}
      >
        <div className="flex min-w-0 flex-1 items-center gap-5 sm:gap-[22px]">
          <PlayerAvatar
            size="xl"
            headshotUrl={player.headshot_url}
            teamColor={team?.primary_color ?? null}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[13px] font-semibold text-ink-2">
              {team && <TeamLogo team={team} className="h-5 w-5" />}
              <span>
                {team ? team.name : "No team"} · {player.sport}
              </span>
            </div>
            <h1 className="my-1 font-display text-[42px] font-bold uppercase leading-[0.95] tracking-[0.015em] sm:text-[54px]">
              {player.name}
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
              <StatusPill injuryStatus={player.injury_status} active={player.active} />
            </div>
          </div>
        </div>
        <NextGameBlock nextGame={player.next_game} hasTeam={team !== null} />
      </div>

      {profile.tracked && (
        <Tiles
          sport={player.sport}
          entries={entries}
          tiles={[FPTS, ...profile.tiles]}
          season={season}
        />
      )}
    </section>
  );
}

export function NextGameBlock({
  nextGame,
  hasTeam,
}: {
  nextGame: NextGame | null;
  hasTeam: boolean;
}) {
  if (!hasTeam) return null;

  return (
    <div
      aria-label="Next game"
      className="flex-none rounded-xl border border-line bg-surface px-4 py-3 md:min-w-[250px]"
    >
      <div className="text-[11.5px] font-bold uppercase tracking-[0.08em] text-ink-2">
        {nextGame?.status === "in_progress" ? "Playing now" : "Next game"}
      </div>
      {nextGame ? (
        <div className="mt-1.5 flex items-center gap-3">
          <TeamLogo team={nextGame.opponent} className="h-10 w-10" />
          <div>
            <div className="font-semibold">
              {nextGame.is_home ? "vs" : "@"} {nextGame.opponent.name}
            </div>
            <div className="text-[13px] text-ink-2">
              {formatGameDateTime(nextGame.start_time)}
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-1.5 text-[13px] text-ink-2">No upcoming games scheduled</div>
      )}
    </div>
  );
}

export function Tiles({
  sport,
  entries,
  tiles,
  season = null,
}: {
  sport: Sport;
  entries: PlayerGameStatsEntry[];
  tiles: string[];
  /** When given, each tile shows the season total and its rank (dashes until there is one). */
  season?: SeasonSummary | null;
}) {
  const total = entries.length;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-[1.25fr_repeat(4,1fr)]">
      {tiles.map((key, index) => {
        const label = STAT_LABELS[key];
        const first = index === 0;
        const ranked = season?.stats[key === FPTS ? "fantasy_points" : key] ?? null;

        return (
          <div
            key={key}
            role="group"
            aria-label={label.name}
            className={`min-w-0 border-line-2 px-4 py-4 sm:px-[22px] ${
              first
                ? "col-span-2 border-b bg-accent-soft lg:col-span-1 lg:border-b-0"
                : "border-t lg:border-t-0 lg:border-l"
            } ${!first && index % 2 === 0 ? "border-l lg:border-l" : ""}`}
          >
            <div className="text-[11.5px] font-bold uppercase tracking-[0.08em] text-ink-2">
              {key === FPTS || sport === "NFL" ? label.name : label.abbr}{" "}
              <span className="font-semibold normal-case tracking-normal text-ink-3">
                · Season
              </span>
            </div>
            <div
              className={`font-display font-bold leading-[1.05] ${
                first ? "text-[52px] text-accent" : "text-[44px]"
              }`}
            >
              {ranked ? formatStat(ranked.total) : "—"}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-ink-3">
              {ranked && season ? (
                <RankLine ranked={ranked} season={season} />
              ) : (
                <span>{total === 0 ? "No games yet" : "Not ranked"}</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Where a season total ranks among the same position: "#3 of 32 QB", "T-#1" when tied. */
function RankLine({ ranked, season }: { ranked: RankedStat; season: SeasonSummary }) {
  const top = ranked.rank <= 5;

  return (
    <>
      <span
        className={`rounded-full px-[7px] py-px text-xs font-bold ${
          top ? "bg-good-soft text-good" : "bg-surface-2 text-ink-2"
        }`}
      >
        {ranked.tied ? "T-" : ""}#{ranked.rank}
      </span>
      <span>
        of {season.pool_size} {displayPosition(season.position_group)}
      </span>
    </>
  );
}
