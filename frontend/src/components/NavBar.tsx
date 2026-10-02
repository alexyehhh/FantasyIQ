"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/players", label: "Players" },
  { href: "/start", label: "Start / Sit" },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <header className="border-b border-white/10 bg-nav text-white">
      <div className="flex h-14 w-full items-center gap-3 px-4 sm:gap-7 sm:px-6">
        <Link
          href="/"
          aria-label="FantasyIQ home"
          className="flex items-center gap-2 font-display text-2xl font-bold uppercase leading-none tracking-wide"
        >
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-base text-on-accent">
            IQ
          </span>
          <span className="hidden sm:inline">
            Fantasy<span className="text-[#c9b8ff]">IQ</span>
          </span>
        </Link>
        <nav aria-label="Primary" className="ml-auto flex h-full">
          {LINKS.map((link) => {
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`-mb-px flex items-center border-b-[3px] px-2.5 text-sm font-semibold sm:px-3.5 ${
                  active
                    ? "border-accent text-white"
                    : "border-transparent text-[#b9b0da] hover:text-white"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <button
          type="button"
          disabled
          aria-label="Profile (coming soon)"
          title="Coming soon"
          className="grid h-9 w-9 flex-none cursor-not-allowed place-items-center rounded-full bg-white/10 text-[#b9b0da] opacity-60"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c0-4.4 3.6-8 8-8s8 3.6 8 8" />
          </svg>
        </button>
      </div>
    </header>
  );
}
