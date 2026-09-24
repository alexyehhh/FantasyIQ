/**
 * The one-line "FPTS uses ... scoring" note under a game log, written from the backend's
 * ScoringConfig so the weights are never copied into the frontend.
 */

import type { Bracket, ScoringConfig } from "./api";
import { STAT_LABELS, type StatProfile } from "./stats";

// Player weights that belong to a kicker's line, not a skill player's.
const KICKER_STATS = new Set([
  "field_goals_made",
  "field_goals_missed",
  "extra_points_made",
  "extra_points_missed",
]);

function statName(key: string): string {
  const label = STAT_LABELS[key];
  if (label) return label.name;
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function signed(points: number): string {
  if (points === 0) return "0";
  return `${points < 0 ? "−" : "+"}${Math.abs(points)}`;
}

function range({ min, max }: Bracket): string {
  if (min !== null && max !== null) return min === max ? String(min) : `${min}–${max}`;
  if (min !== null) return `${min}+`;
  return max !== null ? `up to ${max}` : "any";
}

function brackets(label: string, list: Bracket[], unit: string): string | null {
  if (list.length === 0) return null;
  const terms = list.map((bracket) => `${range(bracket)}${unit} ${signed(bracket.points)}`);
  return `${label} ${terms.join(", ")}`;
}

function weights(entries: [string, number][]): string[] {
  return entries.map(([stat, weight]) => `${statName(stat)} ${signed(weight)}`);
}

export function describeScoring(
  config: ScoringConfig,
  kind: StatProfile["scoringKind"],
): string {
  const player = Object.entries(config.player_weights);
  let terms: (string | null)[];
  if (kind === "defense") {
    terms = [
      ...weights(Object.entries(config.defense_weights)),
      brackets("Points allowed", config.points_allowed, ""),
    ];
  } else if (kind === "kicker") {
    terms = [
      brackets("Field goals made", config.field_goal_made, " yds"),
      brackets("missed", config.field_goal_missed, " yds"),
      ...weights(player.filter(([stat]) => KICKER_STATS.has(stat))),
    ];
  } else {
    terms = weights(player.filter(([stat]) => !KICKER_STATS.has(stat)));
  }
  return `FPTS uses ${config.name} scoring: ${terms.filter(Boolean).join(", ")}.`;
}
