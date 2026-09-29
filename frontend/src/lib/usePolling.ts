"use client";

import { useEffect, useRef } from "react";

/**
 * How often the homepage's live-ish widgets (scores, top scorers, news) re-fetch. Matches
 * LiveRefresh's cadence, which is how often the backend's live lane can update a game.
 */
export const POLL_INTERVAL_MS = 30_000;

/**
 * Calls `fetchFn` on a fixed interval, pausing while the tab is hidden and catching up
 * immediately when it's shown again — same idea as LiveRefresh, but for a component that
 * manages its own state from a plain fetch instead of router.refresh(). Does not call
 * `fetchFn` on mount; the caller's own effect handles the first load.
 */
export function usePolling(fetchFn: () => void, intervalMs: number = POLL_INTERVAL_MS): void {
  // A ref keeps the latest callback available to the interval without having to restart it
  // (and re-wait a full interval) every time the caller passes a new function identity.
  const fetchRef = useRef(fetchFn);
  fetchRef.current = fetchFn;

  useEffect(() => {
    const tick = () => {
      if (!document.hidden) fetchRef.current();
    };
    const onVisibilityChange = () => {
      if (!document.hidden) tick();
    };

    const timer = setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [intervalMs]);
}
