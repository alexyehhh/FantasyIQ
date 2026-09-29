"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import PlayerAvatar from "@/components/PlayerAvatar";
import { getHeadlines, type HeadlineEntry, type Sport } from "@/lib/api";
import { displayPosition } from "@/lib/positions";
import { usePolling } from "@/lib/usePolling";

const SPORTS: Sport[] = ["NFL", "NBA"];
const COUNT = 12;

const KIND_LABEL: Record<HeadlineEntry["kind"], string> = {
  performance: "Performance",
  injury: "Injury",
};

/** Real headlines about fantasy-relevant players: standout stat lines and reported injury
 * news, built from data already on file — not designations, and not random bench players.
 * Re-fetches in the background every 30s (see usePolling) so a new report shows up on its
 * own; injuries only update on the backend every 15 minutes, but polling faster is cheap and
 * keeps this in step with the other homepage widgets. */
export default function NewsList() {
  const [sport, setSport] = useState<Sport>("NFL");
  const [items, setItems] = useState<HeadlineEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  const load = useCallback(
    (silent = false) => {
      const id = ++requestId.current;
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      getHeadlines(sport, COUNT)
        .then((res) => {
          if (id === requestId.current) setItems(res.items);
        })
        .catch((err: Error) => {
          if (id === requestId.current && !silent) setError(err.message);
        })
        .finally(() => {
          if (id === requestId.current && !silent) setLoading(false);
        });
    },
    [sport],
  );

  useEffect(() => {
    load();
  }, [load]);

  usePolling(() => load(true));

  return (
    <section aria-label="News" className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-bold uppercase leading-none tracking-wide">
            News
          </h2>
          <p className="mt-1 text-xs text-ink-3">Standout performances and real injury news.</p>
        </div>
        <div role="group" aria-label="Sport" className="flex rounded-[10px] bg-surface-2 p-1">
          {SPORTS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={sport === option}
              onClick={() => setSport(option)}
              className={`h-7 rounded-lg px-3 text-xs font-bold ${
                sport === option ? "bg-accent text-on-accent" : "text-ink-3 hover:text-ink"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3 max-h-[440px] min-h-0 flex-1 overflow-y-auto rounded-xl border border-line-2">
        {loading ? (
          <p role="status" className="p-5 text-sm text-ink-3">
            Loading…
          </p>
        ) : error ? (
          <p role="alert" className="p-5 text-sm text-bad">
            {error}
          </p>
        ) : items.length === 0 ? (
          <p role="status" className="p-5 text-sm text-ink-3">
            No fantasy news right now.
          </p>
        ) : (
          <ol>
            {items.map((entry, index) => (
              <li key={`${entry.kind}-${entry.player_id}-${index}`} className="border-b border-line-2 last:border-b-0">
                <Link
                  href={`/players/${entry.player_id}`}
                  className="flex items-start gap-2.5 px-3 py-2.5 hover:bg-surface-2"
                >
                  <PlayerAvatar
                    headshotUrl={entry.headshot_url}
                    teamColor={entry.team?.primary_color ?? null}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                      <span
                        className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                          entry.kind === "injury" ? "bg-warn-soft text-warn" : "bg-good-soft text-good"
                        }`}
                      >
                        {KIND_LABEL[entry.kind]}
                      </span>
                      <span className="text-xs font-semibold text-ink-3">
                        {entry.player_name}
                        {entry.position ? ` · ${displayPosition(entry.position)}` : ""}
                        {entry.team ? ` · ${entry.team.abbreviation}` : ""}
                      </span>
                    </span>
                    <span className="mt-1 block text-sm text-ink">{entry.headline}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
