"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listPlayers, type PlayerSummary, type Sport } from "@/lib/api";

export default function PlayersPage() {
  const [search, setSearch] = useState("");
  const [sport, setSport] = useState<Sport | "">("");
  const [players, setPlayers] = useState<PlayerSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timeout = setTimeout(() => {
      setLoading(true);
      setError(null);
      listPlayers({
        search: search || undefined,
        sport: sport || undefined,
        limit: 50,
      })
        .then((res) => {
          setPlayers(res.items);
          setTotal(res.total);
        })
        .catch(() => setError("Could not load players. Is the backend running?"))
        .finally(() => setLoading(false));
    }, 250);

    return () => clearTimeout(timeout);
  }, [search, sport]);

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-bold">Players</h1>

      <div className="mt-6 flex gap-3">
        <input
          type="text"
          placeholder="Search by name..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded border border-gray-300 px-3 py-2"
        />
        <select
          value={sport}
          onChange={(e) => setSport(e.target.value as Sport | "")}
          className="rounded border border-gray-300 px-3 py-2"
        >
          <option value="">All sports</option>
          <option value="NBA">NBA</option>
          <option value="NFL">NFL</option>
        </select>
      </div>

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {!error && loading && <p className="mt-4 text-sm text-gray-500">Loading…</p>}
      {!error && !loading && players.length === 0 && (
        <p className="mt-4 text-sm text-gray-500">No players found.</p>
      )}

      <ul className="mt-4 divide-y divide-gray-200 rounded border border-gray-200 bg-white">
        {players.map((player) => (
          <li key={player.id}>
            <Link
              href={`/players/${player.id}`}
              className="flex items-center justify-between px-4 py-3 hover:bg-gray-100"
            >
              <span>
                <span className="font-medium">{player.name}</span>
                {player.position && (
                  <span className="ml-2 text-sm text-gray-500">
                    {player.position}
                  </span>
                )}
              </span>
              <span className="text-sm text-gray-500">{player.sport}</span>
            </Link>
          </li>
        ))}
      </ul>

      {!error && !loading && total > players.length && (
        <p className="mt-3 text-sm text-gray-500">
          Showing {players.length} of {total} players. Refine your search to
          narrow results.
        </p>
      )}
    </main>
  );
}
