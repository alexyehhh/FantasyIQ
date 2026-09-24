import type { InjuryReport } from "@/lib/api";
import { formatGameDate } from "@/lib/format";

const OUT_STATUSES = /^(out|injured reserve|ir|suspended)/i;

export default function InjuryNote({ injury }: { injury: InjuryReport }) {
  const tone = OUT_STATUSES.test(injury.status)
    ? "bg-bad-soft text-bad"
    : "bg-warn-soft text-warn";

  return (
    <section
      aria-label="Player note"
      className="mt-5 flex items-start gap-3.5 rounded-2xl border border-line bg-surface p-5 shadow-panel"
    >
      <span className={`grid h-9 w-9 flex-none place-items-center rounded-[10px] ${tone}`}>
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.6"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M12 5v14M5 12h14" />
        </svg>
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <b>{injury.status}</b>
          {injury.type && <span className="text-ink-2">· {injury.type}</span>}
          {injury.updated_at && (
            <span className="text-xs text-ink-3 sm:ml-auto">
              Updated {formatGameDate(injury.updated_at)}
            </span>
          )}
        </div>
        {injury.note && <p className="mt-1 text-ink-2">{injury.note}</p>}
      </div>
    </section>
  );
}
