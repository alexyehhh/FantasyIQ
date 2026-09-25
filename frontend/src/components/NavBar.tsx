import Link from "next/link";

export default function NavBar() {
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
          <Link
            href="/players"
            className="-mb-px flex items-center border-b-[3px] border-transparent px-3.5 text-sm font-semibold text-[#b9b0da] hover:text-white"
          >
            Players
          </Link>
          <Link
            href="/start"
            className="-mb-px flex items-center border-b-[3px] border-transparent px-3.5 text-sm font-semibold text-[#b9b0da] hover:text-white"
          >
            Start / Sit
          </Link>
        </nav>
      </div>
    </header>
  );
}
