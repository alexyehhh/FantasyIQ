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
      <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-7 px-4">
        <Link
          href="/"
          aria-label="FantasyIQ home"
          className="flex items-center gap-2 font-display text-2xl font-bold uppercase leading-none tracking-wide"
        >
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-base text-on-accent">
            IQ
          </span>
          <span>
            Fantasy<span className="text-[#c9b8ff]">IQ</span>
          </span>
        </Link>
        <nav aria-label="Primary" className="flex h-full">
          {LINKS.map((link) => {
            const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`-mb-px flex items-center border-b-[3px] px-3.5 text-sm font-semibold ${
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
      </div>
    </header>
  );
}
