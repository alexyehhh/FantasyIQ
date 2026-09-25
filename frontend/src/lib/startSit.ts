/**
 * The logic behind the "Who should I start?" page: lineup slots, scoring choices, and turning
 * projections into a verdict. Kept apart from the components so it can be tested without a DOM.
 * The projections themselves (and their spreads) come from the backend; nothing here computes
 * fantasy points.
 */

import type { ProjectionEntry, ScoringConfig, Sport } from "./api";

// ---------------------------------------------------------------------------------------------
// Lineup slots and sources

export interface Slot {
  /** What the backend calls it (GET /projections/top?slot=). */
  id: string;
  label: string;
}

export const SLOTS: Record<Sport, Slot[]> = {
  NFL: [
    { id: "QB", label: "QB" },
    { id: "RB", label: "RB" },
    { id: "WR", label: "WR" },
    { id: "TE", label: "TE" },
    { id: "FLEX", label: "FLEX" },
    { id: "SUPERFLEX", label: "Superflex" },
    { id: "K", label: "K" },
    { id: "DST", label: "DST" },
  ],
  NBA: [
    { id: "G", label: "G" },
    { id: "F", label: "F" },
    { id: "C", label: "C" },
    { id: "UTIL", label: "Util" },
  ],
};

/** The most players that can be compared at once. */
export const MAX_COMPARED = 5;

/** Used until the backend's list of sources arrives. */
export const FALLBACK_SOURCES = [
  { name: "sleeper", label: "Sleeper", description: "", sports: ["NBA", "NFL"] as Sport[] },
];

// ---------------------------------------------------------------------------------------------
// Scoring choices

export type ScoringChoice = "default" | "half" | "standard" | "custom";

export interface ScoringOption {
  id: ScoringChoice;
  label: string;
}

export function scoringOptions(sport: Sport): ScoringOption[] {
  return sport === "NFL"
    ? [
        { id: "default", label: "FantasyIQ (PPR)" },
        { id: "half", label: "Half-PPR" },
        { id: "standard", label: "Standard" },
        { id: "custom", label: "Custom" },
      ]
    : [
        { id: "default", label: "FantasyIQ" },
        { id: "custom", label: "Custom" },
      ];
}

/** The weights offered for editing under "Custom", in the order they're shown. */
export const EDITABLE_WEIGHTS: Record<Sport, { key: string; label: string }[]> = {
  NFL: [
    { key: "passing_yards", label: "Passing yard" },
    { key: "passing_touchdowns", label: "Passing TD" },
    { key: "interceptions", label: "Interception" },
    { key: "rushing_yards", label: "Rushing yard" },
    { key: "rushing_touchdowns", label: "Rushing TD" },
    { key: "receptions", label: "Reception" },
    { key: "receiving_yards", label: "Receiving yard" },
    { key: "receiving_touchdowns", label: "Receiving TD" },
    { key: "fumbles_lost", label: "Fumble lost" },
  ],
  NBA: [
    { key: "points", label: "Point" },
    { key: "rebounds", label: "Rebound" },
    { key: "assists", label: "Assist" },
    { key: "steals", label: "Steal" },
    { key: "blocks", label: "Block" },
    { key: "turnovers", label: "Turnover" },
  ],
};

/**
 * The scoring config to send for a choice, built from the sport's default (`base`) so the
 * kicker and defense scoring always stay the league's. `null` means "the default": send nothing.
 */
export function scoringFor(
  choice: ScoringChoice,
  base: ScoringConfig | null,
  customWeights: Record<string, number>,
): ScoringConfig | null {
  if (choice === "default" || base === null) return null;
  if (choice === "half" || choice === "standard") {
    const receptions = choice === "half" ? 0.5 : 0;
    return {
      ...base,
      name: choice === "half" ? "Half-PPR" : "Standard",
      player_weights: { ...base.player_weights, receptions },
    };
  }
  return { ...base, name: "Custom", player_weights: { ...base.player_weights, ...customWeights } };
}

// ---------------------------------------------------------------------------------------------
// Turning projections into advice

const SQRT2 = Math.SQRT2;

/** Error function (Abramowitz & Stegun 7.1.26, accurate to about 1e-7). */
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const poly =
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t;
  return sign * (1 - poly * Math.exp(-x * x));
}

interface Scored {
  fantasy_points: number | null;
  std: number | null;
}

/** The chance that `a` scores more than `b`, with scores normally spread around the projections. */
export function winProbability(a: Scored, b: Scored): number {
  const spread = Math.hypot(a.std ?? 0, b.std ?? 0);
  const gap = (a.fantasy_points ?? 0) - (b.fantasy_points ?? 0);
  if (spread === 0) return gap === 0 ? 0.5 : gap > 0 ? 1 : 0;
  return 0.5 * (1 + erf(gap / (spread * SQRT2)));
}

export type Edge = "clear" | "lean" | "toss-up";

export function edgeFor(chance: number): Edge {
  const lead = Math.max(chance, 1 - chance);
  return lead >= 0.7 ? "clear" : lead >= 0.55 ? "lean" : "toss-up";
}

export const EDGE_LABEL: Record<Edge, string> = {
  clear: "Clear edge",
  lean: "Lean",
  "toss-up": "Toss-up",
};

export function percent(chance: number): string {
  return `${Math.round(chance * 100)}%`;
}

export function points(value: number | null): string {
  return value === null ? "–" : value.toFixed(1);
}

/**
 * "WR · SEA @ WSH" (away) or "RB · DET vs NYJ" (home): position, team and opponent. Without a
 * game it is just position and team.
 */
export function matchupLine(entry: {
  position: string | null;
  team: { abbreviation: string } | null;
  game: { is_home: boolean; opponent: { abbreviation: string } } | null;
}): string {
  const position = entry.position === "PK" ? "K" : (entry.position ?? "–");
  if (!entry.team) return position;
  const team = `${position} · ${entry.team.abbreviation}`;
  if (!entry.game) return team;
  return `${team} ${entry.game.is_home ? "vs" : "@"} ${entry.game.opponent.abbreviation}`;
}

/** Players are ranked by points; anyone without a number goes last, in the order given. */
export function rankEntries(entries: ProjectionEntry[]): ProjectionEntry[] {
  const withPoints = entries
    .filter((entry) => entry.fantasy_points !== null)
    .sort((a, b) => (b.fantasy_points ?? 0) - (a.fantasy_points ?? 0));
  return [...withPoints, ...entries.filter((entry) => entry.fantasy_points === null)];
}

/**
 * True once the entry's game has started or finished: they're locked into whoever's lineup they
 * are in and can no longer be started or benched.
 */
export function isLocked(entry: Pick<ProjectionEntry, "game">): boolean {
  return entry.game !== null && entry.game.status !== "scheduled";
}

/** What to call a locked player's situation. */
export function lockedLabel(entry: Pick<ProjectionEntry, "game">): string {
  return entry.game?.status === "final" ? "Game over" : "Game in progress";
}

export interface Advice {
  /** Everyone, in the order to show them: startable players by points, then locked ones, then
   * those with no projection. */
  ranked: ProjectionEntry[];
  /** The first `spots` players who can still be started. */
  starters: ProjectionEntry[];
  /** The other players who can still be started, best first. */
  sitters: ProjectionEntry[];
  /** Players with a projection whose game has started: compared, but never recommended. */
  locked: ProjectionEntry[];
  /** How likely the last starter is to outscore the first sitter; null if none sit. */
  cutoffChance: number | null;
  edge: Edge | null;
}

/**
 * Ranks the players and picks who to start. Players whose game is over (or under way) still get
 * their numbers, so they can be compared, but they can't be started and take no part in the
 * verdict.
 */
export function buildAdvice(entries: ProjectionEntry[], spots: number): Advice {
  const scored = rankEntries(entries).filter((entry) => entry.fantasy_points !== null);
  const startable = scored.filter((entry) => !isLocked(entry));
  const locked = scored.filter(isLocked);
  const unscored = entries.filter((entry) => entry.fantasy_points === null);

  const places = Math.min(spots, Math.max(startable.length - 1, 1));
  const starters = startable.slice(0, places);
  const sitters = startable.slice(places);
  const lastStarter = starters[starters.length - 1];
  const cutoffChance =
    sitters[0] && lastStarter ? winProbability(lastStarter, sitters[0]) : null;
  return {
    ranked: [...startable, ...locked, ...unscored],
    starters,
    sitters,
    locked,
    cutoffChance,
    edge: cutoffChance === null ? null : edgeFor(cutoffChance),
  };
}

/** "Jahmyr Gibbs", "Gibbs and Lamb", "Gibbs, Lamb and Chase". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export interface Reason {
  tone: "good" | "warn" | "info";
  text: string;
}

const OUT = /^(out|injured reserve|ir|suspended)/i;

/**
 * Why an entry sits where it does, from the numbers and flags the backend gave us: the biggest
 * things first, and never more than four. `ranked` is every player being compared.
 */
export function explain(entry: ProjectionEntry, ranked: ProjectionEntry[]): Reason[] {
  const reasons: Reason[] = [];
  const points_ = entry.fantasy_points;

  if (isLocked(entry) && points_ !== null) {
    return [
      {
        tone: "warn",
        text: `${lockedLabel(entry)}: they can't be started any more, so they're only here for comparison.`,
      },
    ];
  }
  if (entry.status === "out") {
    return [{ tone: "warn", text: `Ruled out (${entry.injury_status ?? "out"}): projects 0.` }];
  }
  if (entry.status === "no_game") {
    return [{ tone: "warn", text: entry.notes[0] ?? "No game to project." }];
  }
  if (entry.status === "unavailable" || points_ === null) {
    return [{ tone: "warn", text: entry.notes[0] ?? "This source has no projection for them." }];
  }

  if (entry.injury_status) {
    reasons.push({
      tone: "warn",
      text: `Listed ${entry.injury_status}: projected as if they play, so check their status.`,
    });
  }

  const rivals = ranked.filter(
    (other) => other !== entry && other.fantasy_points !== null && !isLocked(other),
  );
  const best = rivals.filter((other) => (other.fantasy_points ?? 0) > points_)[0];
  const next = rivals.filter((other) => (other.fantasy_points ?? 0) <= points_)[0];
  if (best === undefined && next) {
    reasons.push({
      tone: "good",
      text: `${points(points_ - (next.fantasy_points ?? 0))} points ahead of ${next.name}.`,
    });
  } else if (best) {
    reasons.push({
      tone: "info",
      text: `${points((best.fantasy_points ?? 0) - points_)} points behind ${best.name}.`,
    });
  }

  const std = entry.std;
  const others = rivals.map((other) => other.std).filter((value): value is number => value != null);
  if (std != null && others.length > 0) {
    const typical = others.reduce((sum, value) => sum + value, 0) / others.length;
    if (std >= typical * 1.3) {
      reasons.push({ tone: "info", text: "Bigger swings than the others: a higher ceiling, a lower floor." });
    } else if (std <= typical * 0.75) {
      reasons.push({ tone: "info", text: "Steadier than the others: a safer floor." });
    }
  }

  if (entry.unprojected_stats.length > 0) {
    reasons.push({
      tone: "warn",
      text: `Your scoring counts ${entry.unprojected_stats
        .map((stat) => stat.replace(/_/g, " "))
        .join(", ")}, which this source doesn't project (counted as 0).`,
    });
  }
  if (entry.approximate) {
    reasons.push({
      tone: "info",
      text: "Kick distances only roughly line up with your scoring brackets.",
    });
  }
  const order = { warn: 0, good: 1, info: 2 } as const;
  return reasons.sort((a, b) => order[a.tone] - order[b.tone]).slice(0, 4);
}

export function isOut(status: string | null): boolean {
  return status !== null && OUT.test(status);
}

// ---------------------------------------------------------------------------------------------
// Players chosen to compare, and the saved roster ("My Team")

/** A player or defense picked for the comparison, with just what's needed to draw its card. */
export interface Candidate {
  kind: "player" | "defense";
  id: number;
  name: string;
  position: string | null;
  team: import("./api").TeamSummary | null;
  headshot_url: string | null;
  injury_status: string | null;
}

export function candidateKey(candidate: Pick<Candidate, "kind" | "id">): string {
  return `${candidate.kind}:${candidate.id}`;
}

export function fromEntry(entry: ProjectionEntry): Candidate {
  return {
    kind: entry.kind,
    id: entry.id,
    name: entry.name,
    position: entry.position,
    team: entry.team,
    headshot_url: entry.headshot_url,
    injury_status: entry.injury_status,
  };
}

export function splitByKind(candidates: Pick<Candidate, "kind" | "id">[]) {
  return {
    playerIds: candidates.filter((c) => c.kind === "player").map((c) => c.id),
    defenseIds: candidates.filter((c) => c.kind === "defense").map((c) => c.id),
  };
}

const MY_TEAM_KEY = "fantasyiq.myTeam";

/** The saved roster, per sport, kept in this browser until leagues can be linked. */
export function loadMyTeam(sport: Sport): Pick<Candidate, "kind" | "id">[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(`${MY_TEAM_KEY}.${sport}`) ?? "[]");
    return Array.isArray(saved)
      ? saved.filter((item) => (item?.kind === "player" || item?.kind === "defense") && Number.isInteger(item?.id))
      : [];
  } catch {
    return [];
  }
}

export function saveMyTeam(sport: Sport, team: Pick<Candidate, "kind" | "id">[]): void {
  try {
    window.localStorage.setItem(
      `${MY_TEAM_KEY}.${sport}`,
      JSON.stringify(team.map(({ kind, id }) => ({ kind, id }))),
    );
  } catch {
    // storage blocked (private window): the roster just won't outlive the tab
  }
}

// ---------------------------------------------------------------------------------------------
// The page's state in its address, so a refresh (or a shared link) shows the same comparison

export const DEFAULT_SLOT: Record<Sport, string> = { NFL: "FLEX", NBA: "UTIL" };

export type PickRef = Pick<Candidate, "kind" | "id">;

/** What makes a comparison reproducible; everything else (lists, tabs) is derived or transient. */
export interface PageState {
  sport: Sport;
  slot: string;
  /** null is the current week. */
  week: number | null;
  scoring: ScoringChoice;
  picks: PickRef[];
  /** Whether the advice is open. */
  advice: boolean;
}

const LAST_QUERY_KEY = "fantasyiq.start.last";
const LAST_WEEK = 18;

function positiveInt(text: string): number | null {
  return /^\d+$/.test(text) && Number(text) > 0 ? Number(text) : null;
}

/**
 * The state a query string describes, keeping only what is valid: an unknown sport, slot, scoring
 * or a mangled id is dropped (falling back to the default) rather than breaking the page.
 * Picks are written `p1384` (player) and `d67` (team defense), comma separated, in order.
 */
export function parsePageState(search: string): Partial<PageState> {
  const params = new URLSearchParams(search);
  const state: Partial<PageState> = {};

  const sport = params.get("sport");
  if (sport === "NFL" || sport === "NBA") state.sport = sport;
  const effectiveSport: Sport = state.sport ?? "NFL";

  const slot = params.get("slot")?.toUpperCase();
  if (slot && SLOTS[effectiveSport].some((option) => option.id === slot)) state.slot = slot;

  const week = positiveInt(params.get("week") ?? "");
  if (week !== null && week <= LAST_WEEK && effectiveSport === "NFL") state.week = week;

  const scoring = params.get("scoring");
  if (scoringOptions(effectiveSport).some((option) => option.id === scoring)) {
    state.scoring = scoring as ScoringChoice;
  }

  const picks: PickRef[] = [];
  for (const token of (params.get("picks") ?? "").split(",")) {
    const id = positiveInt(token.slice(1));
    const kind = token[0] === "p" ? "player" : token[0] === "d" ? "defense" : null;
    if (id === null || kind === null) continue;
    if (kind === "defense" && effectiveSport !== "NFL") continue;
    if (picks.some((pick) => pick.kind === kind && pick.id === id)) continue;
    if (picks.length < MAX_COMPARED) picks.push({ kind, id });
  }
  if (picks.length > 0) state.picks = picks;

  if (params.get("advice") === "1" && picks.length >= 2) state.advice = true;
  return state;
}

/** The query string (without the "?") for a state, leaving out everything that is the default. */
export function buildPageQuery(state: PageState): string {
  const parts: string[] = [];
  if (state.sport !== "NFL") parts.push(`sport=${state.sport}`);
  if (state.slot !== DEFAULT_SLOT[state.sport]) parts.push(`slot=${encodeURIComponent(state.slot)}`);
  if (state.week !== null) parts.push(`week=${state.week}`);
  if (state.scoring !== "default") parts.push(`scoring=${state.scoring}`);
  if (state.picks.length > 0) {
    parts.push(`picks=${state.picks.map((p) => (p.kind === "player" ? "p" : "d") + p.id).join(",")}`);
  }
  if (state.advice && state.picks.length >= 2) parts.push("advice=1");
  return parts.join("&");
}

/** The last comparison, kept so coming back to the page without a link picks up where it was left. */
export function loadLastQuery(): string {
  try {
    return window.localStorage.getItem(LAST_QUERY_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveLastQuery(query: string): void {
  try {
    window.localStorage.setItem(LAST_QUERY_KEY, query);
  } catch {
    // storage blocked: only the address remembers it
  }
}
