"use client";

import Link from "next/link";
import PlayerAvatar from "@/components/PlayerAvatar";
import RangePlot from "@/components/startsit/RangePlot";
import type { ProjectionEntry } from "@/lib/api";
import { formatGameDateTime } from "@/lib/format";
import {
  EDGE_LABEL,
  buildAdvice,
  explain,
  isLocked,
  joinNames,
  lockedLabel,
  matchupLine,
  percent,
  points,
} from "@/lib/startSit";

interface AdvicePanelProps {
  /** The projections of the compared players. */
  entries: ProjectionEntry[];
  sourceLabel: string;
  scoringName: string;
  week: number | null;
  spots: number;
  onSpots: (spots: number) => void;
}

const TONE_STYLE = {
  good: "text-good",
  warn: "text-warn",
  info: "text-ink-3",
} as const;
const TONE_MARK = { good: "▲", warn: "!", info: "•" } as const;

const key = (entry: { kind: string; id: number }) => `${entry.kind}:${entry.id}`;

function profileHref(entry: ProjectionEntry): string {
  return entry.kind === "defense" ? `/defenses/${entry.id}` : `/players/${entry.id}`;
}

/** The verdict, the shared range plot, and a card per player saying where they rank and why. */
export default function AdvicePanel({
  entries,
  sourceLabel,
  scoringName,
  week,
  spots,
  onSpots,
}: AdvicePanelProps) {
  const advice = buildAdvice(entries, spots);
  const starterKeys = new Set(advice.starters.map(key));
  const startable = advice.starters.length + advice.sitters.length;
  const lockedNames = advice.locked.map((entry) => entry.name);
  const lockedNote =
    lockedNames.length === 1
      ? ` ${lockedNames[0]} can't be started: the game has already started, so it's shown for comparison only.`
      : lockedNames.length > 1
        ? ` ${joinNames(lockedNames)} can't be started: their games have already started, so they're shown for comparison only.`
        : "";

  let headline = "No projections to compare";
  let detail = "None of these players has a projection from this source.";
  if (advice.starters.length > 0) {
    headline = `Start ${joinNames(advice.starters.map((entry) => entry.name))}`;
    const lastStarter = advice.starters[advice.starters.length - 1];
    const sitter = advice.sitters[0];
    if (sitter && advice.cutoffChance !== null) {
      const subject = advice.starters.length > 1 ? `The last starter, ${lastStarter.name},` : lastStarter.name;
      detail = `${subject} is projected ${points(lastStarter.fantasy_points)} against ${points(
        sitter.fantasy_points,
      )} for ${sitter.name}: about a ${percent(advice.cutoffChance)} chance of finishing ahead.`;
    } else {
      detail =
        startable === 1
          ? `${lastStarter.name} is the only one of these players who can still be started.`
          : "Everyone who can still be started is starting, so there is no one to sit.";
    }
  } else if (advice.locked.length > 0) {
    headline = "Nobody here can be started";
    detail = "Every one of these games has already started, so the numbers are only for comparison.";
  }
  detail += lockedNote;

  return (
    <section
      aria-label="Start/sit advice"
      className="overflow-hidden rounded-2xl border border-line bg-surface shadow-panel"
    >
      <div className="border-b border-line bg-accent-soft p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-ink-2">
          {week !== null ? `Week ${week} · ` : "Next game · "}
          {scoringName} · {sourceLabel}
        </p>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-display text-3xl font-bold uppercase leading-tight tracking-[0.02em] sm:text-4xl">
              {headline}
            </h2>
            <p className="mt-1 max-w-[62ch] text-ink-2">{detail}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {advice.edge && (
              <span
                className={`rounded-full px-3 py-1 text-sm font-bold ${
                  advice.edge === "clear"
                    ? "bg-good-soft text-good"
                    : advice.edge === "lean"
                      ? "bg-warn-soft text-warn"
                      : "bg-surface text-ink-2 ring-1 ring-line"
                }`}
              >
                {EDGE_LABEL[advice.edge]}
              </span>
            )}
            {startable > 2 && (
              <label className="flex items-center gap-2 text-sm font-semibold text-ink-2">
                Starting spots
                <select
                  value={spots}
                  onChange={(event) => onSpots(Number(event.target.value))}
                  className="h-9 rounded-lg border border-line bg-surface px-2 text-ink"
                >
                  {Array.from({ length: startable - 1 }, (_, index) => index + 1).map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>
      </div>

      <div className="border-b border-line p-5">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.08em] text-ink-3">
          Likely range (floor to ceiling)
        </h3>
        <RangePlot entries={advice.ranked} starterIds={starterKeys} />
      </div>

      <div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-3">
        {advice.ranked.map((entry, index) => {
          const starter = starterKeys.has(key(entry));
          const locked = isLocked(entry);
          const reasons = explain(entry, advice.ranked);
          return (
            <article
              key={key(entry)}
              className={`rounded-xl border p-4 ${
                locked
                  ? "border-warn bg-surface-2"
                  : starter
                    ? "border-accent bg-surface"
                    : "border-line bg-surface-2"
              }`}
            >
              {locked && (
                <div className="-mx-1 -mt-1 mb-3 flex items-center gap-2 rounded-lg bg-warn-soft px-3 py-2 text-sm font-bold text-warn">
                  <span aria-hidden="true">⏱</span>
                  {lockedLabel(entry)}: can&rsquo;t be started
                </div>
              )}
              <div className="flex items-start gap-3">
                <PlayerAvatar
                  headshotUrl={entry.headshot_url}
                  teamColor={entry.team?.primary_color ?? null}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span
                      className={`grid h-5 min-w-5 place-items-center rounded-full px-1 text-[11px] font-bold ${
                        starter && !locked ? "bg-accent text-on-accent" : "bg-line text-ink-2"
                      }`}
                    >
                      {index + 1}
                    </span>
                    <Link href={profileHref(entry)} className="truncate font-semibold hover:underline">
                      {entry.name}
                    </Link>
                  </div>
                  <div className="mt-0.5 text-xs text-ink-3">
                    {matchupLine(entry)}
                    {entry.game ? `, ${formatGameDateTime(entry.game.start_time)}` : ""}
                  </div>
                </div>
                {entry.fantasy_points !== null && (
                  <span
                    className={`rounded-md px-2 py-0.5 text-xs font-bold uppercase tracking-wide ${
                      locked
                        ? "bg-warn-soft text-warn"
                        : starter
                          ? "bg-good-soft text-good"
                          : "bg-bad-soft text-bad"
                    }`}
                  >
                    {locked ? (entry.game?.status === "final" ? "Final" : "Live") : starter ? "Start" : "Sit"}
                  </span>
                )}
              </div>

              <div className="mt-3 flex items-end justify-between gap-3">
                <div>
                  <div className="font-display text-4xl font-bold leading-none">
                    {points(entry.fantasy_points)}
                  </div>
                  <div className="mt-1 text-xs text-ink-3">
                    {entry.low !== null && entry.high !== null
                      ? `Floor ${points(entry.low)} · Ceiling ${points(entry.high)}`
                      : "projected points"}
                  </div>
                </div>
                {entry.chance_best !== null && (
                  <div className="text-right">
                    <div className="text-lg font-bold leading-none">{percent(entry.chance_best)}</div>
                    <div className="mt-1 text-xs text-ink-3">chance to score most</div>
                  </div>
                )}
              </div>

              <ul className="mt-3 space-y-1.5 border-t border-line pt-3 text-[13px] leading-snug">
                {reasons.map((reason) => (
                  <li key={reason.text} className={`flex gap-2 ${TONE_STYLE[reason.tone]}`}>
                    <span aria-hidden="true" className="w-3 flex-none text-center font-bold">
                      {TONE_MARK[reason.tone]}
                    </span>
                    <span className={reason.tone === "info" ? "text-ink-2" : ""}>{reason.text}</span>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>

      <p className="border-t border-line px-5 py-3 text-xs leading-relaxed text-ink-3">
        Floor and ceiling are one standard deviation either side of the projection, from each
        player&rsquo;s own recent games where there are enough and a typical spread for their
        position otherwise. The chance to score most assumes scores are spread normally around
        the projections. None of this knows about news that broke after the source updated.
      </p>
    </section>
  );
}
