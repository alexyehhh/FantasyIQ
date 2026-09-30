"use client";

import { useEffect, useMemo, useState } from "react";
import AccuracyChart from "@/components/AccuracyChart";
import {
  getAccuracy,
  getScoringPreset,
  type AccuracyResponse,
  type ScoringConfig,
  type Sport,
} from "@/lib/api";
import {
  POSITION_FILTERS,
  formatBias,
  formatCorrelation,
  formatMiss,
  orderedSources,
  sourceColor,
  sourceLabel,
  verdict,
} from "@/lib/accuracy";
import { scoringFor, scoringOptions, type ScoringChoice } from "@/lib/startSit";

const SPORTS: Sport[] = ["NFL", "NBA"];
// Custom weights aren't offered here: the point is comparing sources, not tuning a league.
const CHOICES = (sport: Sport) => scoringOptions(sport).filter((option) => option.id !== "custom");

export default function AccuracyPage() {
  const [sport, setSport] = useState<Sport>("NFL");
  const [position, setPosition] = useState<string | null>(null);
  const [choice, setChoice] = useState<ScoringChoice>("default");
  const [base, setBase] = useState<ScoringConfig | null>(null);
  const [report, setReport] = useState<AccuracyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const scoring = useMemo(() => scoringFor(choice, base, {}), [choice, base]);
  const scoringKey = JSON.stringify(scoring);

  useEffect(() => {
    let cancelled = false;
    getScoringPreset(sport)
      .then((preset) => !cancelled && setBase(preset))
      .catch(() => !cancelled && setBase(null));
    return () => {
      cancelled = true;
    };
  }, [sport]);

  useEffect(() => {
    // Half-PPR and Standard are built from the sport's default, so wait for it to arrive.
    if (choice !== "default" && base === null) return;
    let cancelled = false;
    setLoading(true);
    getAccuracy({ sport, position, scoring })
      .then((next) => {
        if (cancelled) return;
        setReport(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load accuracy");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // `scoringKey` stands in for `scoring`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sport, position, scoringKey, choice, base]);

  const changeSport = (next: Sport) => {
    setSport(next);
    setPosition(null);
    setChoice("default");
  };

  const summary = report ? verdict(report) : null;
  const sources = report ? orderedSources(report.sources) : [];
  const chartable = report !== null && report.series.length > 0 && sources.length > 0;

  return (
    <main className="mx-auto w-full max-w-5xl px-4 pb-16 pt-6 sm:px-6">
      <h1 className="font-display text-4xl font-bold uppercase tracking-wide">Accuracy</h1>
      <p className="mt-1 max-w-2xl text-sm text-ink-2">
        How close each source&apos;s projections came to what actually happened. Projections are
        saved before kickoff, so a source can&apos;t have seen the result, and sources are compared
        only on the players and defenses every one of them projected.
      </p>

      <div className="mt-5 flex flex-wrap items-end gap-x-6 gap-y-3" aria-label="Filters" role="group">
        <div role="group" aria-label="Sport" className="inline-flex gap-0.5 rounded-[10px] border border-line bg-surface-2 p-[3px]">
          {SPORTS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={sport === option}
              onClick={() => changeSport(option)}
              className={`rounded-[7px] px-3.5 py-1.5 text-[13px] font-semibold ${
                sport === option ? "bg-surface text-ink shadow" : "text-ink-2 hover:text-ink"
              }`}
            >
              {option}
            </button>
          ))}
        </div>

        <div role="group" aria-label="Position" className="flex flex-wrap gap-2">
          {[null, ...POSITION_FILTERS[sport]].map((option) => (
            <button
              key={option ?? "all"}
              type="button"
              aria-pressed={position === option}
              onClick={() => setPosition(option)}
              className={`rounded-full border px-[13px] py-1.5 text-[13px] font-semibold ${
                position === option
                  ? "border-accent bg-accent text-on-accent"
                  : "border-line bg-surface text-ink-2 hover:border-accent hover:text-ink"
              }`}
            >
              {option ?? "All"}
            </button>
          ))}
        </div>

        <label className="flex items-center gap-2 text-[13px] font-semibold text-ink-2">
          Scoring
          <select
            value={choice}
            onChange={(event) => setChoice(event.target.value as ScoringChoice)}
            className="h-9 rounded-[10px] border border-line bg-surface px-2.5 text-sm font-semibold text-ink"
          >
            {CHOICES(sport).map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p role="alert" className="mt-5 rounded-xl border border-line bg-bad-soft px-4 py-3 text-sm text-bad">
          {error}
        </p>
      )}

      <div className={`mt-5 space-y-5 transition-opacity ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
        {report && summary && (
          <section
            aria-label="Summary"
            className="rounded-2xl border border-line bg-surface px-4 py-4 shadow-panel sm:px-5"
          >
            <p
              className={`text-base font-semibold ${
                summary.kind === "closer" || summary.kind === "tie" ? "text-ink" : "text-ink-2"
              }`}
            >
              {summary.text}
            </p>
            {report.compared > 0 && (
              <p className="mt-1 text-[12.5px] text-ink-3">
                {report.compared} player-games compared under {report.scoring}
                {report.did_not_play > 0 &&
                  `; ${report.did_not_play} projected players who didn't play aren't counted`}
                .
              </p>
            )}
          </section>
        )}

        {chartable && report && <AccuracyChart report={report} />}

        {report && report.by_position.length > 0 && (
          <section
            aria-label="By position"
            className="rounded-2xl border border-line bg-surface shadow-panel"
          >
            <h2 className="px-4 pt-4 font-display text-xl font-semibold uppercase tracking-[0.06em] sm:px-5">
              By position
            </h2>
            <div className="overflow-x-auto px-4 pb-4 pt-2 sm:px-5">
              <table className="w-full min-w-[520px] border-collapse text-sm">
                <caption className="sr-only">
                  Accuracy by position: average miss, bias and ranking agreement per source
                </caption>
                <thead>
                  <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-3">
                    <th scope="col" className="py-2 pr-3 font-semibold">Position</th>
                    <th scope="col" className="py-2 pr-3 text-right font-semibold">Players</th>
                    {sources.map((source) => (
                      <th key={source} scope="col" className="py-2 pr-3 text-right font-semibold">
                        <span className="inline-flex items-center gap-1.5">
                          <i className="h-2.5 w-2.5 rounded-[3px]" style={{ background: sourceColor(source) }} />
                          {sourceLabel(source)}
                          <span className="font-normal normal-case text-ink-3">miss · bias · rank</span>
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.by_position.map((row) => (
                    <tr key={row.position} className="border-b border-line-2 align-top">
                      <th scope="row" className="py-2 pr-3 text-left font-medium">
                        {row.position}
                        {!row.enough_data && (
                          <span className="ml-2 rounded bg-warn-soft px-1.5 py-0.5 text-[10.5px] font-semibold uppercase text-warn">
                            few games
                          </span>
                        )}
                      </th>
                      <td className="py-2 pr-3 text-right tabular-nums text-ink-2">{row.n}</td>
                      {sources.map((source) => {
                        const totals = row.sources[source];
                        return (
                          <td key={source} className="py-2 pr-3 text-right tabular-nums">
                            <b>{formatMiss(totals?.mae)}</b>
                            <span className="text-ink-3">
                              {" · "}
                              {totals ? formatBias(totals.bias) : "—"}
                              {" · "}
                              {formatCorrelation(totals?.rank_corr)}
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-3 text-[12px] leading-relaxed text-ink-3">
                <b>Miss</b> is the average gap in fantasy points (lower is better). <b>Bias</b> is
                how far a source runs high (+) or low (−) on average. <b>Rank</b> is how well its
                order of players matched the real order each week (1 is perfect).
              </p>
            </div>
          </section>
        )}

        {report && report.notes.length > 0 && report.compared > 0 && (
          <ul className="space-y-1 text-[12.5px] text-ink-3">
            {report.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
