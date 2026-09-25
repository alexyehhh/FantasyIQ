"use client";

import { useEffect, useId, useRef, useState } from "react";
import PlayerAvatar from "@/components/PlayerAvatar";
import { listDefenses, listPlayers, type Sport } from "@/lib/api";
import { displayPosition } from "@/lib/positions";
import { candidateKey, type Candidate } from "@/lib/startSit";

interface PlayerSearchProps {
  sport: Sport;
  /** Keys of the players already chosen, which are marked and can't be picked again. */
  pickedKeys: Set<string>;
  full: boolean;
  onPick: (candidate: Candidate) => void;
}

const MIN_CHARS = 2;

/** "Add a player": type a name, pick from the matches. Team defenses match too (NFL). */
export default function PlayerSearch({ sport, pickedKeys, full, onPick }: PlayerSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const listId = useId();
  const searching = query.trim().length >= MIN_CHARS;

  useEffect(() => {
    if (!searching) return;
    let stale = false;
    const timeout = setTimeout(async () => {
      setLoading(true);
      setFailed(false);
      try {
        const [players, defenses] = await Promise.all([
          listPlayers({ sport, search: query.trim(), sort: "fantasy_points", limit: 8 }),
          sport === "NFL"
            ? listDefenses({ search: query.trim(), limit: 3 })
            : Promise.resolve({ items: [] }),
        ]);
        if (stale) return;
        setResults([
          ...players.items.map(
            (p): Candidate => ({
              kind: "player",
              id: p.id,
              name: p.name,
              position: p.position,
              team: p.team,
              headshot_url: p.headshot_url,
              injury_status: p.injury_status,
            }),
          ),
          ...defenses.items.map(
            (d): Candidate => ({
              kind: "defense",
              id: d.id,
              name: `${d.name} D/ST`,
              position: "DEF",
              team: d,
              headshot_url: null,
              injury_status: null,
            }),
          ),
        ]);
        setActive(0);
      } catch {
        if (!stale) setFailed(true);
      } finally {
        if (!stale) setLoading(false);
      }
    }, 220);
    return () => {
      stale = true;
      clearTimeout(timeout);
    };
  }, [query, searching, sport]);

  const shown = searching ? results : [];

  const pick = (candidate: Candidate) => {
    if (pickedKeys.has(candidateKey(candidate)) || full) return;
    onPick(candidate);
    setQuery("");
    setResults([]);
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(index + 1, shown.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && shown[active]) {
      event.preventDefault();
      pick(shown[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div
      ref={boxRef}
      className="relative"
      onBlur={(event) => {
        if (!boxRef.current?.contains(event.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <div className="relative">
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          aria-hidden="true"
          className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-3"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          type="text"
          role="combobox"
          aria-expanded={open && searching}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-label="Add a player"
          placeholder={full ? "Remove a player to add another" : "Add a player"}
          disabled={full}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          className="h-12 w-full rounded-full bg-surface pl-11 pr-4 text-base font-medium text-ink shadow-panel placeholder:text-ink-3 focus:outline focus:outline-2 focus:outline-offset-2 focus:outline-[#c9b8ff] disabled:opacity-70"
        />
      </div>

      {open && searching && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Matching players"
          className="absolute left-0 right-0 top-[calc(100%+6px)] z-20 max-h-[360px] overflow-auto rounded-2xl border border-line bg-surface py-1.5 text-ink shadow-panel"
        >
          {loading && shown.length === 0 && (
            <li className="px-4 py-3 text-sm text-ink-3">Searching…</li>
          )}
          {failed && (
            <li className="px-4 py-3 text-sm text-bad">Search failed. Is the backend running?</li>
          )}
          {!loading && !failed && shown.length === 0 && (
            <li className="px-4 py-3 text-sm text-ink-3">No players match “{query.trim()}”.</li>
          )}
          {shown.map((candidate, index) => {
            const taken = pickedKeys.has(candidateKey(candidate));
            return (
              <li
                key={candidateKey(candidate)}
                role="option"
                aria-selected={index === active}
                aria-disabled={taken}
                onMouseEnter={() => setActive(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => pick(candidate)}
                className={`flex cursor-pointer items-center gap-3 px-4 py-2 ${
                  index === active ? "bg-accent-soft" : ""
                } ${taken ? "opacity-50" : ""}`}
              >
                <PlayerAvatar
                  headshotUrl={candidate.headshot_url}
                  teamColor={candidate.team?.primary_color ?? null}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{candidate.name}</span>
                  <span className="block truncate text-xs text-ink-3">
                    {displayPosition(candidate.position) ?? "–"}
                    {candidate.team ? ` · ${candidate.team.abbreviation}` : ""}
                    {candidate.injury_status ? ` · ${candidate.injury_status}` : ""}
                  </span>
                </span>
                <span className="text-xs font-semibold text-ink-3">{taken ? "Added" : "Add"}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
