/**
 * Fantasy scoring: a fantasy score is just a weighted sum of a game's stat
 * line, so a league's own settings (Yahoo, ESPN, ...) can later be dropped in
 * as another `ScoringWeights` without touching any page code.
 */

import type { Sport } from "./api";

export type ScoringWeights = Record<string, number>;

export interface ScoringSystem {
  name: string;
  weights: ScoringWeights;
}

// Only uses stats the backend already stores (see app/db/models/player_game_stats*.py).
export const DEFAULT_SCORING: Record<Sport, ScoringSystem> = {
  NBA: {
    name: "FantasyIQ standard",
    weights: {
      points: 1,
      rebounds: 1.2,
      assists: 1.5,
      steals: 3,
      blocks: 3,
      turnovers: -1,
    },
  },
  NFL: {
    name: "FantasyIQ standard (PPR)",
    weights: {
      passing_yards: 0.04,
      passing_touchdowns: 4,
      interceptions: -2,
      rushing_yards: 0.1,
      rushing_touchdowns: 6,
      receptions: 1,
      receiving_yards: 0.1,
      receiving_touchdowns: 6,
      fumbles_lost: -2,
    },
  },
};

export function fantasyPoints(
  stats: Record<string, number>,
  weights: ScoringWeights,
): number {
  const total = Object.entries(weights).reduce(
    (sum, [stat, weight]) => sum + weight * (stats[stat] ?? 0),
    0,
  );
  return Math.round(total * 10) / 10;
}
