import type { TeamSummary } from "@/lib/api";

interface TeamLogoProps {
  team: TeamSummary;
  className?: string;
}

/** Team logo, or the abbreviation on the team's color when there's no logo. */
export default function TeamLogo({ team, className = "h-6 w-6" }: TeamLogoProps) {
  if (team.logo_url) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={team.logo_url} alt="" className={`${className} flex-none object-contain`} />;
  }
  return (
    <span
      aria-hidden="true"
      className={`${className} grid flex-none place-items-center rounded-full font-display text-[10px] font-semibold text-white`}
      style={{ background: team.primary_color ?? "var(--ink-3)" }}
    >
      {team.abbreviation}
    </span>
  );
}
