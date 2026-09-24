interface StatusPillProps {
  injuryStatus: string | null;
  active: boolean;
}

const OUT_STATUSES = /^(out|injured reserve|ir|suspended)/i;

/** Health at a glance: injury designation if there is one, otherwise roster status. */
export default function StatusPill({ injuryStatus, active }: StatusPillProps) {
  let label = active ? "Active" : "Inactive";
  let tone = active ? "bg-good-soft text-good" : "bg-bad-soft text-bad";
  if (injuryStatus) {
    label = injuryStatus;
    tone = OUT_STATUSES.test(injuryStatus)
      ? "bg-bad-soft text-bad"
      : "bg-warn-soft text-warn";
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone}`}
    >
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}
