/**
 * Display formatting shared by the player pages.
 *
 * Game dates and times are always rendered in US Pacific time. Formatting in
 * the viewer's own timezone would make server-rendered HTML disagree with the
 * browser's (the Next server runs in UTC), so one fixed zone is used instead.
 */

const GAME_TIME_ZONE = "America/Los_Angeles";

export function formatGameDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: GAME_TIME_ZONE,
  });
}

/** e.g. "10:00 AM" */
export function formatGameTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: GAME_TIME_ZONE,
  });
}

/** e.g. "Sun, Sep 27 · 10:00 AM" */
export function formatGameDateTime(iso: string): string {
  const day = new Date(iso).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: GAME_TIME_ZONE,
  });
  return `${day} · ${formatGameTime(iso)}`;
}
