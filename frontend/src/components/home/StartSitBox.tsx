"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import PlayerAvatar from "@/components/PlayerAvatar";
import PlayerSearch from "@/components/startsit/PlayerSearch";
import type { Sport } from "@/lib/api";
import {
  DEFAULT_SLOT,
  MAX_COMPARED,
  buildPageQuery,
  candidateKey,
  type Candidate,
} from "@/lib/startSit";

const SPORTS: Sport[] = ["NFL", "NBA"];

/** A quick way in to "Who should I start?" from the home page: search and add players, then
 * "View advice" hands them straight to the /start page's comparison. */
export default function StartSitBox() {
  const router = useRouter();
  const [sport, setSport] = useState<Sport>("NFL");
  const [picked, setPicked] = useState<Candidate[]>([]);

  const pickedKeys = useMemo(() => new Set(picked.map(candidateKey)), [picked]);
  const full = picked.length >= MAX_COMPARED;
  const ready = picked.length >= 2;

  const chooseSport = (next: Sport) => {
    if (next === sport) return;
    setSport(next);
    setPicked([]);
  };

  const add = (candidate: Candidate) => {
    setPicked((current) => {
      if (current.some((c) => candidateKey(c) === candidateKey(candidate))) return current;
      return current.length >= MAX_COMPARED ? current : [...current, candidate];
    });
  };

  const remove = (candidate: Candidate) => {
    setPicked((current) => current.filter((c) => candidateKey(c) !== candidateKey(candidate)));
  };

  const viewAdvice = () => {
    if (!ready) return;
    const query = buildPageQuery({
      sport,
      slot: DEFAULT_SLOT[sport],
      week: null,
      scoring: "default",
      picks: picked,
      advice: true,
    });
    router.push(`/start?${query}`);
  };

  return (
    <section aria-label="Start or sit" className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-bold uppercase leading-none tracking-wide">
            Who should I start?
          </h2>
          <p className="mt-1 text-xs text-ink-3">Add up to {MAX_COMPARED} players to compare.</p>
        </div>
        <div role="group" aria-label="Sport" className="flex rounded-[10px] bg-surface-2 p-1">
          {SPORTS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={sport === option}
              onClick={() => chooseSport(option)}
              className={`h-7 rounded-lg px-3 text-xs font-bold ${
                sport === option ? "bg-accent text-on-accent" : "text-ink-3 hover:text-ink"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 space-y-3">
        <PlayerSearch sport={sport} pickedKeys={pickedKeys} full={full} onPick={add} />

        {picked.length > 0 && (
          <ul className="flex flex-wrap gap-2">
            {picked.map((candidate) => (
              <li key={candidateKey(candidate)}>
                <span className="flex items-center gap-1.5 rounded-full bg-surface-2 py-1 pl-1 pr-1.5 text-xs font-semibold">
                  <PlayerAvatar
                    headshotUrl={candidate.headshot_url}
                    teamColor={candidate.team?.primary_color ?? null}
                  />
                  <span className="max-w-[110px] truncate">{candidate.name}</span>
                  <button
                    type="button"
                    onClick={() => remove(candidate)}
                    aria-label={`Remove ${candidate.name}`}
                    className="grid h-5 w-5 flex-none place-items-center rounded-full text-ink-3 hover:bg-line hover:text-ink"
                  >
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                      stroke="currentColor"
                      strokeWidth="3"
                      strokeLinecap="round"
                    >
                      <path d="M6 6l12 12M18 6 6 18" />
                    </svg>
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}

        <button
          type="button"
          onClick={viewAdvice}
          disabled={!ready}
          className="h-11 w-full rounded-xl bg-accent px-4 font-display text-base font-semibold uppercase leading-none tracking-wide text-on-accent shadow-panel transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-3 disabled:shadow-none"
        >
          View advice
        </button>
      </div>
    </section>
  );
}
