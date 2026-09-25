"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getHealth } from "@/lib/api";

/** How often a page with a live game re-reads the stats. The backend refreshes a game every ~30 s. */
export const REFRESH_INTERVAL_MS = 30_000;

/**
 * Keeps a page's data current while its team's game is on, without reloading the browser:
 * router.refresh() re-fetches the server-rendered data and updates the page in place, so scroll
 * position, the selected stat and the game-log page are kept. It pauses while the tab is hidden and
 * catches up as soon as the tab is shown again. If the backend can't be reached the page keeps what
 * it has and tries again on the next tick.
 *
 * Mount it only while a game is live (see hasLiveGame): unmounting is what stops it.
 */
export default function LiveRefresh() {
  const router = useRouter();

  useEffect(() => {
    let inFlight = false;

    const refresh = async () => {
      if (document.hidden || inFlight) return;
      inFlight = true;
      try {
        // A page that fails to render can't be refreshed in place, so check the backend first.
        await getHealth();
        router.refresh();
      } catch {
        // Unreachable right now: leave the page as it is.
      } finally {
        inFlight = false;
      }
    };
    const onVisibilityChange = () => {
      if (!document.hidden) void refresh();
    };

    const timer = setInterval(refresh, REFRESH_INTERVAL_MS);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [router]);

  return (
    <span
      role="status"
      className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 text-xs font-semibold text-ink-2"
    >
      <span aria-hidden="true" className="h-2 w-2 animate-pulse rounded-full bg-good" />
      Live · updates automatically
    </span>
  );
}
