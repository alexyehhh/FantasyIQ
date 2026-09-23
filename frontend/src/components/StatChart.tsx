"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PlayerGameStatsEntry, Sport } from "@/lib/api";

// Which stat to chart by default, in priority order, per sport — the
// stats dict shape depends on the player's sport (see app/schemas/players.py).
const PREFERRED_STAT_BY_SPORT: Record<Sport, string[]> = {
  NBA: ["points", "rebounds", "assists"],
  NFL: ["passing_yards", "rushing_yards", "receiving_yards"],
};

function defaultStatKey(sport: Sport, statKeys: string[]): string {
  const preferred = PREFERRED_STAT_BY_SPORT[sport].find((key) =>
    statKeys.includes(key),
  );
  return preferred ?? statKeys[0];
}

interface StatChartProps {
  sport: Sport;
  entries: PlayerGameStatsEntry[];
}

export default function StatChart({ sport, entries }: StatChartProps) {
  const statKeys = useMemo(
    () => (entries[0] ? Object.keys(entries[0].stats) : []),
    [entries],
  );
  const [statKey, setStatKey] = useState(() => defaultStatKey(sport, statKeys));

  if (entries.length === 0 || statKeys.length === 0) {
    return <p className="text-sm text-gray-500">No game stats yet.</p>;
  }

  // The API returns most-recent-first; chart oldest to newest, left to right.
  const data = [...entries].reverse().map((entry) => ({
    date: new Date(entry.game_date).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    value: entry.stats[statKey] ?? 0,
  }));

  return (
    <div>
      <div className="mb-3 flex items-center gap-2">
        <label htmlFor="stat-select" className="text-sm text-gray-600">
          Stat
        </label>
        <select
          id="stat-select"
          value={statKey}
          onChange={(e) => setStatKey(e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
        >
          {statKeys.map((key) => (
            <option key={key} value={key}>
              {key.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis allowDecimals={false} />
          <Tooltip />
          <Line type="monotone" dataKey="value" stroke="#2563eb" strokeWidth={2} dot />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
