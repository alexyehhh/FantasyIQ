"use client";

import { useState } from "react";
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
}: PlayerStatsProps) {
  const profile = profileFor(sport, position);
  const scoringNote = scoring ? describeScoring(scoring, profile.scoringKind) : null;
  const [stat, setStat] = useState(profile.defaultStat);
  const [range, setRange] = useState<ChartRange>(entries.length > 10 ? 10 : "all");
  const rows = buildLogRows(entries, schedule, byeWeek);
  const hasSchedule = rows.length > 0;

  if (!profile.tracked || entries.length === 0) {
    return (
      <div className="mt-5 flex flex-col gap-5">
        <section
          aria-label="Game stats"
          className="rounded-2xl border border-line bg-surface p-8 text-center shadow-panel"
        >
          <h2 className="font-display text-xl font-semibold uppercase tracking-[0.06em]">
            {profile.tracked
              ? "No game stats yet"
              : `${profile.untrackedLabel ?? "Stats"} stats aren't tracked for this position yet`}
          </h2>
          <p className="mt-1 text-ink-2">
            {profile.tracked
              ? "Stats appear here once this player's games have been played and ingested."
              : `${profile.untrackedLabel ?? "Stat"} stats and fantasy points will appear here once they are added.`}
          </p>
        </section>
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

  return (
    <div className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-5">
        <StatChart
          sport={sport}
          entries={entries}
          stat={stat}
          onStatChange={setStat}
          statOptions={profile.rows}
          range={range}
          onRangeChange={setRange}
        />
        <GameLog
          sport={sport}
          rows={rows}
          selectedStat={stat}
          columns={profile.logColumns}
          negativeStats={profile.negativeStats}
          scoringNote={scoringNote}
        />
      </div>
      <aside className="flex min-w-0 flex-col gap-5">
        <AveragesTable
          sport={sport}
          entries={entries}
          rows={profile.rows}
          selectedStat={stat}
        />
        <ConsistencyStrip sport={sport} entries={entries} stat={stat} />
      </aside>
    </div>
  );
}
