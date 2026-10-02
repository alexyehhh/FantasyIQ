import type { AccuracyPlayerGame } from "@/lib/api";
import {
  formatBias,
  formatMiss,
  gameLabel,
  gameMiss,
  projectingSources,
  sourceColor,
  sourceLabel,
  summarize,
} from "@/lib/accuracy";

/**
 * How close each projection source came to this player's real fantasy points, game by game, and on
 * average. Projections are saved before kickoff, so a source can't have seen the result.
 */
export default function PlayerAccuracy({ games }: { games: AccuracyPlayerGame[] }) {
  if (games.length === 0) return null;
  const sources = projectingSources(games);
  const summary = summarize(games);

  return (
    <section aria-label="Projection accuracy" className="rounded-2xl border border-line bg-surface shadow-panel">
      <h2 className="px-4 pt-4 font-display text-xl font-semibold uppercase tracking-[0.06em] sm:px-5">
        Projection accuracy
      </h2>
      <div className="px-4 pb-4 pt-2 sm:px-5">
        {summary.n > 0 && sources.length > 1 && (
          <>
            <p className="text-sm font-semibold">
              {summary.best
                ? `${sourceLabel(summary.best)} has been closer over ${summary.n} ${summary.n === 1 ? "game" : "games"}.`
                : `No source has been clearly closer over ${summary.n} ${summary.n === 1 ? "game" : "games"}.`}
            </p>
            <dl className="mt-3 flex flex-wrap gap-3">
              {summary.averages.map((average) => (
                <div
                  key={average.source}
                  className={`min-w-[160px] rounded-xl border px-3.5 py-2.5 ${
                    average.source === summary.best ? "border-accent" : "border-line"
                  }`}
                >
                  <dt className="flex items-center gap-1.5 text-[12px] font-semibold text-ink-2">
                    <i className="h-2.5 w-2.5 rounded-[3px]" style={{ background: sourceColor(average.source) }} />
                    {sourceLabel(average.source)}
                  </dt>
                  <dd className="mt-1 text-2xl font-bold tabular-nums">
                    {formatMiss(average.mae)}
                    <span className="ml-1 text-[12px] font-normal text-ink-3">avg miss</span>
                  </dd>
                  <dd className="text-[12px] text-ink-3">bias {formatBias(average.bias)}</dd>
                </div>
              ))}
            </dl>
          </>
        )}

        <div className="mt-4 max-h-[240px] overflow-auto">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <caption className="sr-only">
              Actual fantasy points and each source&apos;s projection and miss per game
            </caption>
            <thead>
              <tr className="sticky top-0 border-b border-line bg-surface text-left text-[11px] uppercase tracking-wider text-ink-3">
                <th scope="col" className="py-2 pr-3 font-semibold">Game</th>
                <th scope="col" className="py-2 pr-3 text-right font-semibold">Actual</th>
                {sources.map((source) => (
                  <th key={source} scope="col" className="py-2 pr-3 text-right font-semibold">
                    <span className="inline-flex items-center gap-1.5">
                      <i className="h-2.5 w-2.5 rounded-[3px]" style={{ background: sourceColor(source) }} />
                      {sourceLabel(source)}
                      <span className="font-normal normal-case text-ink-3">proj · miss</span>
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {games.map((game) => (
                <tr key={game.game_id} className="border-b border-line-2">
                  <th scope="row" className="py-2 pr-3 text-left font-medium">
                    {gameLabel(game)}
                    <span className="ml-2 font-normal text-ink-3">
                      {game.home ? "vs" : "@"} {game.opponent ?? "—"}
                    </span>
                  </th>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {game.played ? <b>{formatMiss(game.actual)}</b> : <span className="text-ink-3">DNP</span>}
                  </td>
                  {sources.map((source) => {
                    const miss = gameMiss(game, source);
                    return (
                      <td key={source} className="py-2 pr-3 text-right tabular-nums">
                        <b>{formatMiss(game.projected[source])}</b>
                        <span className="text-ink-3">
                          {" · "}
                          {miss === null ? "—" : formatBias(miss)}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[12px] leading-relaxed text-ink-3">
            <b>Miss</b> is projected minus actual: + ran high, − ran low. The average miss ignores
            the sign (lower is better) and counts only games the player played that every source
            projected.
          </p>
        </div>
      </div>
    </section>
  );
}
