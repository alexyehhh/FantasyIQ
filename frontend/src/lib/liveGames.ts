/**
 * When a page should keep itself up to date: while its team has a game on, or one that is about to
 * start or should just have (the backend worker marks a game in progress within about half a
 * minute of kickoff, so the page has to be watching to notice).
 */

import type { ScheduleEntry } from "./api";

const MINUTE = 60_000;
/** Start watching this long before kickoff... */
export const LEAD_MS = 10 * MINUTE;
/** ...and, for a game the schedule still calls upcoming, this long after it. */
export const GRACE_MS = 30 * MINUTE;

export function hasLiveGame(
  schedule: Pick<ScheduleEntry, "status" | "game_date">[],
  now: number,
): boolean {
  return schedule.some((game) => {
    if (game.status === "in_progress") return true;
    if (game.status !== "scheduled") return false;
    const start = Date.parse(game.game_date);
    return start - LEAD_MS <= now && now <= start + GRACE_MS;
  });
}
