/**
 * The logic behind the accuracy page: naming and coloring the sources, turning the API's report
 * into chart rows, and saying in words who is closer (or that there isn't enough data to say).
 */

import type { AccuracyResponse, Sport } from "./api";

/** Below this many compared player-games a report can't say which source is better. */
export const MIN_SAMPLE = 50;

const LABELS: Record<string, string> = {
  fantasyiq: "FantasyIQ model",
  sleeper: "Sleeper",
};

export function sourceLabel(name: string): string {
  return LABELS[name] ?? name;
}

/**
 * A source's color, fixed by who it is and never by its rank, so filtering never repaints it: our
 * model is the app's violet and every outside source the orange (only one is compared today).
 */
export function sourceColor(name: string): string {
  return name === "fantasyiq" ? "var(--series-model)" : "var(--series-other)";
}

/** Our model first, then the others, so legends and tables keep one order. */
export function orderedSources(sources: string[]): string[] {
  return [...sources].sort((a, b) => Number(b === "fantasyiq") - Number(a === "fantasyiq") || a.localeCompare(b));
}

export const POSITION_FILTERS: Record<Sport, string[]> = {
  NFL: ["QB", "RB", "WR", "TE", "K"],
  NBA: ["G", "F", "C"],
};

/** Fantasy points with one decimal, "—" when there is nothing to show. */
export function formatMiss(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(1);
}

/** A bias with its sign: "+1.2" projects too high, "−0.4" too low. */
export function formatBias(value: number): string {
  if (Math.abs(value) < 0.05) return "0.0";
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}`;
}

export function formatCorrelation(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(2);
}

export interface ChartRow {
  key: string;
  label: string;
  n: number;
  [source: string]: number | string;
}

/** One row per week, each source's average miss under its own name, for the line chart. */
export function chartRows(report: AccuracyResponse): ChartRow[] {
  return report.series.map((point) => ({
    key: point.key,
    label: point.label,
    n: point.n,
    ...point.mae,
  }));
}

export interface Verdict {
  kind: "empty" | "thin" | "closer" | "tie";
  text: string;
}

/** Who was closer overall, only when there is enough data to say. */
export function verdict(report: AccuracyResponse): Verdict {
  if (report.compared === 0) {
    return {
      kind: "empty",
      text: "No finished games have saved projections yet. They are saved before kickoff, so this fills in as games are played.",
    };
  }
  const sources = orderedSources(Object.keys(report.overall));
  if (!report.enough_data) {
    return {
      kind: "thin",
      text: `Only ${report.compared} player-games so far. Under ${MIN_SAMPLE} is too few to say which source is better.`,
    };
  }
  if (sources.length < 2) {
    return { kind: "thin", text: "Only one source has saved projections, so there is nothing to compare." };
  }
  const ranked = [...sources].sort((a, b) => report.overall[a].mae - report.overall[b].mae);
  const [best, next] = ranked;
  const gap = report.overall[next].mae - report.overall[best].mae;
  if (gap < 0.05) {
    return {
      kind: "tie",
      text: `${sourceLabel(best)} and ${sourceLabel(next)} are tied, both missing by about ${formatMiss(report.overall[best].mae)} points on average.`,
    };
  }
  return {
    kind: "closer",
    text: `${sourceLabel(best)} is closer: it misses by ${formatMiss(report.overall[best].mae)} points on average, ${formatMiss(gap)} fewer than ${sourceLabel(next)}.`,
  };
}
