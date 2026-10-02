"use client";

import { useState, type ReactNode } from "react";
import type { PlayerGameStatsEntry, ScheduleEntry, ScoringConfig, Sport } from "@/lib/api";
import { buildLogRows } from "@/lib/gameLog";
import { describeScoring } from "@/lib/scoringNote";
import { profileFor } from "@/lib/stats";
import AveragesTable from "./AveragesTable";
import ConsistencyStrip from "./ConsistencyStrip";
import GameLog from "./GameLog";
import StatChart, { type ChartRange } from "./StatChart";

interface PlayerStatsProps {
  sport: Sport;
  position: string | null;
  /** Every game the player has a stat line for, most recent first, as the API returns them. */
  entries: PlayerGameStatsEntry[];
  /** The player's team's games this season, played and upcoming. */
  schedule: ScheduleEntry[];
  byeWeek: number | null;
  /** The default scoring FPTS is computed under, for the note under the game log. */
  scoring?: ScoringConfig | null;
  /** A box shown with the trend, in the column beside the averages (the projection accuracy). */
  accuracy?: ReactNode;
}

/**
 * The stats half of a player page. Chart, averages, consistency strip and game
 * log all follow one selected stat, so it is held here rather than in each.
 */
export default function PlayerStats({
  sport,
  position,
  entries,
  schedule,
  byeWeek,
  scoring = null,
  accuracy = null,
}: PlayerStatsProps) {
  const profile = profileFor(sport, position);
  const scoringNote = scoring ? describeScoring(scoring, profile.scoringKind) : null;
  const [stat, setStat] = useState(profile.defaultStat);
  // A game still being played has only a running total, which would drag down the averages and
  // the spread and skew the trend, so those use finished games only. The game log lists every
  // game with a stat line, the one in progress marked live.
  const completed = entries.filter((entry) => entry.status === "final");
  const [range, setRange] = useState<ChartRange>(completed.length > 10 ? 10 : "all");
  const rows = buildLogRows(entries, schedule, byeWeek);
  const hasSchedule = rows.length > 0;
  const onlyLive = entries.length > 0 && completed.length === 0;

  if (!profile.tracked || completed.length === 0) {
    return (
      <div className="mt-5 flex flex-col gap-5">
        <section
          aria-label="Game stats"
          className="rounded-2xl border border-line bg-surface p-8 text-center shadow-panel"
        >
          <h2 className="font-display text-xl font-semibold uppercase tracking-[0.06em]">
            {profile.tracked
              ? onlyLive
                ? "No completed games yet"
                : "No game stats yet"
              : `${profile.untrackedLabel ?? "Stats"} stats aren't tracked for this position yet`}
          </h2>
          <p className="mt-1 text-ink-2">
            {profile.tracked
              ? onlyLive
                ? "The trend, averages and spread appear once a game has finished. The game in progress is in the log below."
                : "Stats appear here once this season's games have been played. Earlier seasons aren't counted."
              : `${profile.untrackedLabel ?? "Stat"} stats and fantasy points will appear here once they are added.`}
          </p>
        </section>
        {accuracy}
        {hasSchedule && (
          <GameLog
            sport={sport}
            rows={rows}
            selectedStat={stat}
            showStats={profile.tracked}
            columns={profile.logColumns}
            negativeStats={profile.negativeStats}
            scoringNote={scoringNote}
          />
        )}
      </div>
    );
  }

  // Boxes sit in rows of equal height, so neighbours start and end level with no empty space under
  // either. The game log spans the page below. Without an accuracy box the trend runs down beside
  // the averages and the consistency strip instead.
  const grid = "grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)] [&>section]:min-w-0";
  const trend = (
    <StatChart
      entries={completed}
      stat={stat}
      onStatChange={setStat}
      statOptions={profile.rows}
      range={range}
      onRangeChange={setRange}
    />
  );
  const averages = (
    <AveragesTable sport={sport} entries={completed} rows={profile.rows} selectedStat={stat} />
  );
  const consistency = <ConsistencyStrip entries={completed} stat={stat} />;
  return (
    <div className="mt-5 flex flex-col gap-5">
      {accuracy ? (
        <>
          <div className={grid}>
            {trend}
            {averages}
          </div>
          <div className={grid}>
            {accuracy}
            {consistency}
          </div>
        </>
      ) : (
        <div className={`${grid} lg:grid-rows-[auto_1fr]`}>
          <div className="min-w-0 lg:row-span-2 [&>section]:h-full">{trend}</div>
          {averages}
          {consistency}
        </div>
      )}
      <GameLog
        sport={sport}
        rows={rows}
        selectedStat={stat}
        columns={profile.logColumns}
        negativeStats={profile.negativeStats}
        scoringNote={scoringNote}
      />
    </div>
  );
}
