/**
 * The position filters offered on the players page, and how positions are
 * written. Filters are fantasy roster slots, not raw position codes: a slot can
 * match several codes (W/R/T is any running back, receiver or tight end).
 */

export interface PositionFilter {
  label: string;
  /** Position codes the backend stores (ESPN's) that this slot matches. */
  positions: string[];
  /** Shown but not selectable yet, with the reason as its tooltip. */
  unavailable?: string;
}

// FB counts as a running back, as in Yahoo.
export const NFL_POSITION_FILTERS: PositionFilter[] = [
  { label: "QB", positions: ["QB"] },
  { label: "RB", positions: ["RB", "FB"] },
  { label: "WR", positions: ["WR"] },
  { label: "TE", positions: ["TE"] },
  { label: "W/R/T", positions: ["RB", "FB", "WR", "TE"] },
  { label: "K", positions: ["PK"] },
  { label: "DEF", positions: [], unavailable: "Team defenses aren't tracked yet" },
];

// ESPN only reports NBA positions as G/F/C (a few players carry the specific PG/SG/SF/PF, which
// are folded in). Exact Yahoo eligibility (PG, SG, SF, PF) has to come from Yahoo later.
// Util is any player, as in Yahoo.
export const NBA_POSITION_FILTERS: PositionFilter[] = [
  { label: "G", positions: ["G", "PG", "SG"] },
  { label: "F", positions: ["F", "SF", "PF"] },
  { label: "C", positions: ["C"] },
  { label: "Util", positions: [] },
];

export function positionFiltersFor(sport: "NFL" | "NBA"): PositionFilter[] {
  return sport === "NFL" ? NFL_POSITION_FILTERS : NBA_POSITION_FILTERS;
}

/** ESPN calls kickers "PK"; fantasy calls them "K". */
export function displayPosition(position: string | null): string | null {
  return position === "PK" ? "K" : position;
}

/** Kickers and punters: the stat lines we store don't describe them. */
export function isSpecialTeamer(position: string | null): boolean {
  return position === "PK" || position === "P";
}
