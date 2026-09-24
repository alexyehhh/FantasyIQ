"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import PlayerAvatar from "@/components/PlayerAvatar";
import StatusPill from "@/components/StatusPill";
import TeamLogo from "@/components/TeamLogo";
import {
  listDefenses,
  listPlayers,
  type DefenseListItem,
  type PlayerListItem,
  type Sport,
} from "@/lib/api";
import { displayPosition, isPunter, positionFiltersFor } from "@/lib/positions";
import { formatStat } from "@/lib/stats";

const SPORT_OPTIONS: Sport[] = ["NFL", "NBA"];
const PAGE_SIZE = 50;

// Team and details drop out progressively so the name never gets squeezed.
const ROW_GRID =
  "grid items-center gap-3 px-4 grid-cols-[minmax(0,1fr)_minmax(0,190px)_64px_56px_70px_92px_22px] max-[860px]:grid-cols-[minmax(0,1fr)_minmax(0,150px)_48px_22px] max-[560px]:grid-cols-[minmax(0,1fr)_52px_44px_22px]";

export default function PlayersPage() {
  const [search, setSearch] = useState("");
  const [sport, setSport] = useState<Sport>("NFL");
  const [positionLabel, setPositionLabel] = useState(positionFiltersFor("NFL")[0].label);
  const [offset, setOffset] = useState(0);
  const [players, setPlayers] = useState<PlayerListItem[]>([]);
  const [defenses, setDefenses] = useState<DefenseListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const filters = positionFiltersFor(sport);
  const activeFilter = filters.find((filter) => filter.label === positionLabel);
  const positions = activeFilter?.positions;
  // The DEF button lists team defenses rather than players.
  const isDefense = activeFilter?.defense === true;
  const shown = isDefense ? defenses.length : players.length;
  const noun = isDefense ? "defenses" : "players";

  // Any change to what's being listed starts again from the top of the ranking.
  const chooseSport = (next: Sport) => {
    setSport(next);
    setPositionLabel(positionFiltersFor(next)[0].label);
    setOffset(0);
  };
  const choosePosition = (label: string) => {
    setPositionLabel(label);
    setOffset(0);
  };
  // The buttons sit at the bottom of a long list, so land back at the top of the next page.
  const turnPage = (nextOffset: number) => {
    setOffset(nextOffset);
    window.scrollTo({ top: 0 });
  };
  const changeSearch = (value: string) => {
    setSearch(value);
    setOffset(0);
  };

  useEffect(() => {
    const timeout = setTimeout(() => {
      setLoading(true);
      setError(null);
      const request = isDefense
        ? listDefenses({
            search: search || undefined,
            sort: "fantasy_points",
            limit: PAGE_SIZE,
            offset,
          }).then((res) => {
            setDefenses(res.items);
            setPlayers([]);
            setTotal(res.total);
          })
        : listPlayers({
            search: search || undefined,
            sport,
            positions,
            sort: "fantasy_points",
            limit: PAGE_SIZE,
            offset,
          }).then((res) => {
            setPlayers(res.items);
            setDefenses([]);
            setTotal(res.total);
          });
      request
        .catch(() => setError(`Could not load ${noun}. Is the backend running?`))
        .finally(() => setLoading(false));
    }, 250);

    return () => clearTimeout(timeout);
  }, [search, sport, positions, offset, isDefense, noun]);

  return (
    <main className="mx-auto max-w-[1120px] px-4 pb-14 pt-6">
      <div className="mb-[18px]">
        <h1 className="font-display text-4xl font-bold uppercase leading-none tracking-[0.02em] sm:text-[44px]">
          Players
        </h1>
        <p className="mt-1.5 text-ink-2">
          Search NFL and NBA players and open a full stat page.
        </p>
      </div>

      <section
        aria-label="Player search"
        className="overflow-hidden rounded-2xl border border-line bg-surface shadow-panel"
      >
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-3.5">
          <div className="relative min-w-[240px] flex-1">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              aria-hidden="true"
              className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              type="text"
              placeholder="Search by name..."
              aria-label="Search players by name"
              value={search}
              onChange={(e) => changeSearch(e.target.value)}
              className="h-10 w-full rounded-[10px] border border-line bg-surface-2 pl-[38px] pr-3 text-sm font-medium text-ink placeholder:text-ink-3 focus:bg-surface focus:outline focus:outline-2 focus:outline-accent"
            />
          </div>
          <div
            role="group"
            aria-label="Sport"
            className="inline-flex gap-0.5 rounded-[10px] border border-line bg-surface-2 p-[3px]"
          >
            {SPORT_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={sport === option}
                onClick={() => chooseSport(option)}
                className={`rounded-[7px] px-[13px] py-1.5 text-[13px] font-semibold ${
                  sport === option
                    ? "bg-surface text-ink shadow"
                    : "text-ink-2 hover:text-ink"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div
          role="group"
          aria-label="Position"
          className="flex gap-2 overflow-x-auto border-b border-line px-3.5 py-3"
        >
          {filters.map((filter) => (
            <button
              key={filter.label}
              type="button"
              aria-pressed={positionLabel === filter.label}
              disabled={filter.unavailable !== undefined}
              title={filter.unavailable}
              onClick={() => choosePosition(filter.label)}
              className={`flex-none rounded-full border px-4 py-1.5 text-[13px] font-semibold disabled:cursor-not-allowed disabled:opacity-45 ${
                positionLabel === filter.label
                  ? "border-accent bg-accent text-on-accent"
                  : "border-line bg-surface text-ink-2 enabled:hover:border-accent enabled:hover:text-ink"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <div
          className={`${ROW_GRID} h-9 border-b border-line bg-surface-2 text-[11.5px] font-bold uppercase tracking-[0.08em] text-ink-3`}
        >
          <span>{isDefense ? "Defense" : "Player"}</span>
          <span>Team</span>
          <span>Pos</span>
          <span className="max-[860px]:hidden">{isDefense ? "Bye" : "#"}</span>
          <span className="max-[860px]:hidden">FPTS</span>
          <span className="max-[860px]:hidden">Status</span>
          <span />
        </div>

        {error && <p className="p-4 text-sm text-bad">{error}</p>}
        {!error && loading && <p className="p-4 text-sm text-ink-3">Loading…</p>}
        {!error && !loading && shown === 0 && (
          <div className="px-4 py-12 text-center text-ink-2">
            <b>No {noun} found</b>
            <br />
            Try a different name or switch the sport filter.
          </div>
        )}

        <ul>
          {defenses.map((defense) => (
            <li key={defense.id} className="border-b border-line-2 last:border-b-0">
              <Link
                href={`/defenses/${defense.id}`}
                className={`${ROW_GRID} min-h-[60px] hover:bg-surface-2`}
              >
                <span className="flex min-w-0 items-center gap-3">
                  <TeamLogo team={defense} className="h-9 w-9" />
                  <span className="truncate text-[15px] font-semibold">{defense.name}</span>
                </span>
                <span className="truncate text-ink-2">{defense.abbreviation}</span>
                <span className="font-bold">DEF</span>
                <span className="tabular-nums max-[860px]:hidden">
                  {defense.bye_week !== null ? `Wk ${defense.bye_week}` : "—"}
                </span>
                <span className="font-semibold tabular-nums max-[860px]:hidden">
                  {defense.fantasy_points !== null ? formatStat(defense.fantasy_points) : "—"}
                </span>
                <span className="max-[860px]:hidden" />
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  className="text-ink-3"
                >
                  <path d="m9 6 6 6-6 6" />
                </svg>
              </Link>
            </li>
          ))}
          {players.map((player) => (
            <li key={player.id} className="border-b border-line-2 last:border-b-0">
              <Link
                href={`/players/${player.id}`}
                className={`${ROW_GRID} min-h-[60px] hover:bg-surface-2`}
              >
                <span className="flex min-w-0 items-center gap-3">
                  <PlayerAvatar
                    headshotUrl={player.headshot_url}
                    teamColor={player.team?.primary_color ?? null}
                  />
                  <span className="truncate text-[15px] font-semibold">{player.name}</span>
                </span>
                <span className="flex min-w-0 items-center gap-2 text-ink-2">
                  {player.team ? (
                    <>
                      <TeamLogo team={player.team} className="h-5 w-5" />
                      <span className="truncate max-[560px]:hidden">{player.team.name}</span>
                      <span className="hidden max-[560px]:inline">
                        {player.team.abbreviation}
                      </span>
                    </>
                  ) : (
                    "—"
                  )}
                </span>
                <span className="font-bold">{displayPosition(player.position) ?? "—"}</span>
                <span className="tabular-nums max-[860px]:hidden">
                  {player.jersey_number !== null ? `#${player.jersey_number}` : "—"}
                </span>
                <span className="font-semibold tabular-nums max-[860px]:hidden">
                  {player.fantasy_points !== null && !isPunter(player.position)
                    ? formatStat(player.fantasy_points)
                    : "—"}
                </span>
                <span className="max-[860px]:hidden">
                  <StatusPill injuryStatus={player.injury_status} active={player.active} />
                </span>
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  className="text-ink-3"
                >
                  <path d="m9 6 6 6-6 6" />
                </svg>
              </Link>
            </li>
          ))}
        </ul>

        {!error && !loading && total > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
            <span className="text-[12.5px] text-ink-3">
              Showing {offset + 1}–{offset + shown} of {total} {noun}, most fantasy points
              first
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => turnPage(Math.max(0, offset - PAGE_SIZE))}
                className="rounded-[9px] border border-line px-4 py-2 text-[13px] font-semibold enabled:hover:border-accent enabled:hover:text-accent disabled:cursor-not-allowed disabled:opacity-45"
              >
                Previous {PAGE_SIZE}
              </button>
              <button
                type="button"
                disabled={offset + shown >= total}
                onClick={() => turnPage(offset + PAGE_SIZE)}
                className="rounded-[9px] border border-line px-4 py-2 text-[13px] font-semibold enabled:hover:border-accent enabled:hover:text-accent disabled:cursor-not-allowed disabled:opacity-45"
              >
                Next {PAGE_SIZE}
              </button>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
