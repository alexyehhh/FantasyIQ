"use client";

import PlayerAvatar from "@/components/PlayerAvatar";
import StatusPill from "@/components/StatusPill";
import { displayPosition } from "@/lib/positions";
import { candidateKey, MAX_COMPARED, type Candidate } from "@/lib/startSit";

interface SlotCardsProps {
  picked: Candidate[];
  savedKeys: Set<string>;
  advising: boolean;
  onRemove: (candidate: Candidate) => void;
  onToggleSaved: (candidate: Candidate) => void;
  onAdvise: () => void;
}

function Star({ filled }: { filled: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"
        fill={filled ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The players being compared, as cards, and the button that asks for the advice. */
export default function SlotCards({
  picked,
  savedKeys,
  advising,
  onRemove,
  onToggleSaved,
  onAdvise,
}: SlotCardsProps) {
  const empty = Array.from({ length: Math.max(MAX_COMPARED - picked.length, 0) });
  const ready = picked.length >= 2;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-[repeat(5,minmax(0,1fr))_150px]">
      {picked.map((candidate) => {
        const saved = savedKeys.has(candidateKey(candidate));
        return (
          <div
            key={candidateKey(candidate)}
            className="relative flex flex-col items-center rounded-2xl border border-white/10 bg-white/[0.06] px-2 pb-3 pt-4 text-center"
          >
            <button
              type="button"
              onClick={() => onRemove(candidate)}
              aria-label={`Remove ${candidate.name}`}
              className="absolute right-1.5 top-1.5 grid h-7 w-7 place-items-center rounded-full text-[#b9b0da] hover:bg-white/10 hover:text-white"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
            <button
              type="button"
              onClick={() => onToggleSaved(candidate)}
              aria-label={saved ? `Remove ${candidate.name} from My Team` : `Save ${candidate.name} to My Team`}
              aria-pressed={saved}
              className={`absolute left-1.5 top-1.5 grid h-7 w-7 place-items-center rounded-full hover:bg-white/10 ${
                saved ? "text-[#ffd166]" : "text-[#b9b0da] hover:text-white"
              }`}
            >
              <Star filled={saved} />
            </button>
            <PlayerAvatar
              headshotUrl={candidate.headshot_url}
              teamColor={candidate.team?.primary_color ?? null}
              size="xl"
            />
            <div className="mt-2 w-full truncate px-1 text-sm font-semibold text-white">
              {candidate.name}
            </div>
            <div className="text-xs text-[#b9b0da]">
              {displayPosition(candidate.position) ?? "–"}
              {candidate.team ? ` · ${candidate.team.abbreviation}` : ""}
            </div>
            {candidate.injury_status && (
              <div className="mt-1.5">
                <StatusPill injuryStatus={candidate.injury_status} active />
              </div>
            )}
          </div>
        );
      })}

      {empty.map((_, index) => (
        <div
          key={`empty-${index}`}
          aria-hidden="true"
          className="flex flex-col items-center justify-end rounded-2xl border border-dashed border-white/15 px-2 pb-3 pt-4"
        >
          <svg viewBox="0 0 40 40" className="h-[92px] w-[92px] opacity-30">
            <circle cx="20" cy="15" r="7.5" fill="white" />
            <path d="M4 40c1.2-9.5 7.5-14.5 16-14.5S34.8 30.5 36 40z" fill="white" />
          </svg>
          <div className="mt-2 text-xs text-[#8f86b8]">Add a player</div>
        </div>
      ))}

      <div className="col-span-2 flex items-center sm:col-span-3 lg:col-span-1">
        <button
          type="button"
          onClick={onAdvise}
          disabled={!ready || advising}
          className="h-14 w-full rounded-xl bg-accent px-4 font-display text-xl font-semibold uppercase leading-none tracking-wide text-on-accent shadow-panel transition hover:brightness-110 disabled:cursor-not-allowed disabled:bg-white/15 disabled:text-[#b9b0da] disabled:shadow-none"
        >
          {advising ? "Working…" : "View advice"}
        </button>
      </div>
    </div>
  );
}
