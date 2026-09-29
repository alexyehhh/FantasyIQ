/** Stands in for the live matchup and roster view until Yahoo Fantasy access is connected. */
export default function MatchupPlaceholder() {
  return (
    <section
      aria-label="Your matchup"
      className="flex h-full flex-col items-center justify-center gap-3 py-10 text-center"
    >
      <div className="grid h-12 w-12 place-items-center rounded-full bg-accent-soft text-accent">
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M8 21h8M12 17v4M17 3H7a2 2 0 0 0-2 2v3a5 5 0 0 0 5 5h4a5 5 0 0 0 5-5V5a2 2 0 0 0-2-2Z" />
          <path d="M5 5H3a2 2 0 0 0-2 2v1a3 3 0 0 0 3 3M19 5h2a2 2 0 0 1 2 2v1a3 3 0 0 1-3 3" />
        </svg>
      </div>
      <h2 className="font-display text-xl font-bold uppercase tracking-wide text-ink">
        Your team &amp; matchup
      </h2>
      <p className="max-w-[36ch] text-sm text-ink-3">
        Once Yahoo Fantasy access is connected, your league&apos;s current matchups and your own
        roster will show up here.
      </p>
    </section>
  );
}
