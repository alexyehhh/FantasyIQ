"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import AdvicePanel from "@/components/startsit/AdvicePanel";
import PlayerSearch from "@/components/startsit/PlayerSearch";
import ProjectionList from "@/components/startsit/ProjectionList";
import ScoringSettings from "@/components/startsit/ScoringSettings";
import SlotCards from "@/components/startsit/SlotCards";
import {
  getProjectionSources,
  getProjections,
  getScoringPreset,
  getTopProjections,
  type ProjectionEntry,
  type ProjectionSource,
  type ScoringConfig,
  type Sport,
} from "@/lib/api";
import {
  DEFAULT_SLOT,
  FALLBACK_SOURCES,
  MAX_COMPARED,
  SLOTS,
  EDITABLE_WEIGHTS,
  candidateKey,
  fromEntry,
  buildPageQuery,
  loadLastQuery,
  loadMyTeam,
  parsePageState,
  saveLastQuery,
  saveMyTeam,
  scoringFor,
  scoringOptions,
  splitByKind,
  type Candidate,
  type PickRef,
  type ScoringChoice,
} from "@/lib/startSit";

const SPORTS: Sport[] = ["NFL", "NBA"];
const LAST_WEEK = 18;
const PAGE_SIZE = 30;
const CUSTOM_KEY = "fantasyiq.customScoring";

type Tab = "top" | "team";

function loadCustom(sport: Sport): Record<string, number> {
  try {
    const saved = JSON.parse(window.localStorage.getItem(`${CUSTOM_KEY}.${sport}`) ?? "{}");
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

function saveCustom(sport: Sport, weights: Record<string, number>): void {
  try {
    window.localStorage.setItem(`${CUSTOM_KEY}.${sport}`, JSON.stringify(weights));
  } catch {
    // storage blocked: the custom weights just won't outlive the tab
  }
}

const selectClass =
  "h-10 rounded-[10px] bg-surface px-3 text-sm font-semibold text-ink focus:outline focus:outline-2 focus:outline-[#c9b8ff]";

export default function StartPage() {
  const [sport, setSport] = useState<Sport>("NFL");
  const [sources, setSources] = useState<ProjectionSource[]>(FALLBACK_SOURCES);
  const [source, setSource] = useState("sleeper");
  const [baseScoring, setBaseScoring] = useState<ScoringConfig | null>(null);
  const [choice, setChoice] = useState<ScoringChoice>("default");
  const [customWeights, setCustomWeights] = useState<Record<string, number>>({});
  const [week, setWeek] = useState<number | null>(null);
  const [slot, setSlot] = useState(DEFAULT_SLOT.NFL);
  const [tab, setTab] = useState<Tab>("top");
  const [settingsOpen, setSettingsOpen] = useState(false);

  // The address (or, without one, the last visit) says what was being compared. Nothing is
  // fetched, and the address isn't rewritten, until it has been read and the picks restored.
  const [ready, setReady] = useState(false);
  const [restored, setRestored] = useState(false);
  const pending = useRef<{ picks: PickRef[]; advice: boolean }>({ picks: [], advice: false });

  const [picked, setPicked] = useState<Candidate[]>([]);
  const [saved, setSaved] = useState<Pick<Candidate, "kind" | "id">[]>([]);
  const [notice, setNotice] = useState<string | null>(null);

  const [topWeek, setTopWeek] = useState<number | null>(null);
  const [top, setTop] = useState<ProjectionEntry[]>([]);
  const [topTotal, setTopTotal] = useState(0);
  const [topLoading, setTopLoading] = useState(true);
  const [topError, setTopError] = useState<string | null>(null);

  const [team, setTeam] = useState<ProjectionEntry[]>([]);
  const [teamLoading, setTeamLoading] = useState(false);
  const [teamError, setTeamError] = useState<string | null>(null);

  const [showAdvice, setShowAdvice] = useState(false);
  const [adviceEntries, setAdviceEntries] = useState<ProjectionEntry[] | null>(null);
  const [adviceLoading, setAdviceLoading] = useState(false);
  const [adviceError, setAdviceError] = useState<string | null>(null);
  const [adviceScoring, setAdviceScoring] = useState("");
  const [adviceWeek, setAdviceWeek] = useState<number | null>(null);
  const [spots, setSpots] = useState(1);
  const adviceRef = useRef<HTMLDivElement>(null);

  const ids = { source: useId(), scoring: useId() };

  const scoring = useMemo(
    () => scoringFor(choice, baseScoring, customWeights),
    [choice, baseScoring, customWeights],
  );
  // Effects depend on the config's content, not its identity.
  const scoringKey = JSON.stringify(scoring);
  // Which page of the top list is showing. Anything that changes the ranking (sport, slot,
  // source, scoring, week) is a different list, which starts again from its first page.
  const listKey = `${sport}|${slot}|${source}|${scoringKey}|${week}`;
  const [pageState, setPageState] = useState({ key: listKey, offset: 0 });
  const offset = pageState.key === listKey ? pageState.offset : 0;
  const listRef = useRef<HTMLDivElement>(null);
  const goToOffset = (next: number) => {
    setPageState({ key: listKey, offset: next });
    listRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const shownWeek = week ?? topWeek;
  const sportSources = useMemo(
    () => sources.filter((s) => s.sports.includes(sport)),
    [sources, sport],
  );
  const sourceLabel = sources.find((s) => s.name === source)?.label ?? source;

  useEffect(() => {
    const saved = parsePageState(window.location.search || loadLastQuery());
    const startSport = saved.sport ?? "NFL";
    setSport(startSport);
    setSlot(saved.slot ?? DEFAULT_SLOT[startSport]);
    setWeek(saved.week ?? null);
    setChoice(saved.scoring ?? "default");
    pending.current = { picks: saved.picks ?? [], advice: saved.advice ?? false };
    setReady(true);
    if (pending.current.picks.length === 0) setRestored(true);
  }, []);

  // Turns the ids in the address back into players (the address holds ids, the cards need names).
  useEffect(() => {
    if (!ready || restored) return;
    let cancelled = false;
    const { picks, advice } = pending.current;
    getProjections({ sport, source, week, ...splitByKind(picks) })
      .then((res) => {
        if (cancelled) return;
        const found = new Map(res.items.map((entry) => [candidateKey(entry), fromEntry(entry)]));
        const back = picks
          .map((pick) => found.get(candidateKey(pick)))
          .filter((c): c is Candidate => c !== undefined);
        setPicked(back);
        if (advice && back.length >= 2) setShowAdvice(true);
      })
      .catch(() => !cancelled && setNotice("Couldn't restore your players. Add them again."))
      .finally(() => !cancelled && setRestored(true));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, restored]);

  // Keeps the address (and the remembered last visit) in step with the comparison.
  useEffect(() => {
    if (!ready || !restored) return;
    const query = buildPageQuery({
      sport,
      slot,
      week,
      scoring: choice,
      picks: picked,
      advice: showAdvice,
    });
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
    saveLastQuery(query);
  }, [ready, restored, sport, slot, week, choice, picked, showAdvice]);

  // What the browser remembers: the saved roster and custom weights, per sport.
  useEffect(() => {
    setSaved(loadMyTeam(sport));
    setCustomWeights(loadCustom(sport));
  }, [sport]);

  useEffect(() => {
    let cancelled = false;
    getProjectionSources()
      .then((list) => {
        if (cancelled || list.length === 0) return;
        setSources(list);
        setSource((current) => (list.some((s) => s.name === current) ? current : list[0].name));
      })
      .catch(() => undefined); // the built-in list is enough to work with
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setBaseScoring(null);
    getScoringPreset(sport).then((config) => !cancelled && setBaseScoring(config));
    return () => {
      cancelled = true;
    };
  }, [sport]);

  // Top players for the slot.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setTopLoading(true);
    setTopError(null);
    getTopProjections({ sport, slot, source, scoring, week, limit: PAGE_SIZE, offset })
      .then((res) => {
        if (cancelled) return;
        setTop(res.items);
        setTopTotal(res.total ?? res.items.length);
        setTopWeek(res.week);
      })
      .catch((error: Error) => {
        if (cancelled) return;
        setTop([]);
        setTopTotal(0);
        setTopError(error.message);
      })
      .finally(() => !cancelled && setTopLoading(false));
    return () => {
      cancelled = true;
    };
    // `scoringKey` stands in for `scoring`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, listKey, offset]);

  // My Team's projections, only while that tab is open.
  useEffect(() => {
    if (tab !== "team" || saved.length === 0) {
      setTeam([]);
      return;
    }
    let cancelled = false;
    setTeamLoading(true);
    setTeamError(null);
    getProjections({ sport, source, scoring, week, ...splitByKind(saved) })
      .then((res) => !cancelled && setTeam(res.items))
      .catch((error: Error) => {
        if (cancelled) return;
        setTeam([]);
        setTeamError(error.message);
      })
      .finally(() => !cancelled && setTeamLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, saved, sport, source, scoringKey, week]);

  // The advice for the players picked.
  useEffect(() => {
    if (!showAdvice || picked.length < 2) return;
    let cancelled = false;
    setAdviceLoading(true);
    setAdviceError(null);
    getProjections({ sport, source, scoring, week: shownWeek, ...splitByKind(picked) })
      .then((res) => {
        if (cancelled) return;
        setAdviceEntries(res.items);
        setAdviceScoring(res.scoring);
        setAdviceWeek(res.week);
      })
      .catch((error: Error) => !cancelled && setAdviceError(error.message))
      .finally(() => !cancelled && setAdviceLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showAdvice, picked, source, scoringKey, shownWeek, sport]);

  const pickedKeys = useMemo(() => new Set(picked.map(candidateKey)), [picked]);
  const savedKeys = useMemo(() => new Set(saved.map(candidateKey)), [saved]);
  const full = picked.length >= MAX_COMPARED;

  const chooseSport = (next: Sport) => {
    if (next === sport) return;
    setSport(next);
    setSlot(DEFAULT_SLOT[next]);
    setChoice("default");
    setWeek(null);
    setTopWeek(null);
    setPicked([]);
    setShowAdvice(false);
    setAdviceEntries(null);
    setNotice(null);
  };

  const add = useCallback(
    (candidate: Candidate) => {
      setNotice(null);
      setPicked((current) => {
        if (current.some((c) => candidateKey(c) === candidateKey(candidate))) return current;
        return current.length >= MAX_COMPARED ? current : [...current, candidate];
      });
    },
    [],
  );

  const remove = (candidate: Candidate) => {
    setNotice(null);
    setPicked((current) => current.filter((c) => candidateKey(c) !== candidateKey(candidate)));
  };

  const togglePicked = (entry: ProjectionEntry) => {
    const candidate = fromEntry(entry);
    if (pickedKeys.has(candidateKey(candidate))) return remove(candidate);
    if (full) return setNotice(`You can compare up to ${MAX_COMPARED} players at once.`);
    add(candidate);
  };

  const toggleSaved = (candidate: Pick<Candidate, "kind" | "id">) => {
    const next = savedKeys.has(candidateKey(candidate))
      ? saved.filter((c) => candidateKey(c) !== candidateKey(candidate))
      : [...saved, { kind: candidate.kind, id: candidate.id }];
    setSaved(next);
    saveMyTeam(sport, next);
  };

  // The editable weights (the ones the settings panel offers) among a scoring's weights.
  const editable = (weights: Record<string, number>): Record<string, number> =>
    Object.fromEntries(
      EDITABLE_WEIGHTS[sport].filter(({ key }) => key in weights).map(({ key }) => [key, weights[key]]),
    );

  // The weights the current choice is using, which is what the settings panel shows.
  const activeWeights = scoring?.player_weights ?? baseScoring?.player_weights ?? {};

  // Picking a scoring option makes Custom start from it, so switching to Half-PPR and then
  // editing (or choosing Custom) carries that 0.5 reception along.
  const chooseScoring = (next: ScoringChoice) => {
    setChoice(next);
    if (next === "custom") return;
    const chosen = scoringFor(next, baseScoring, {}) ?? baseScoring;
    if (!chosen) return;
    const weights = editable(chosen.player_weights);
    setCustomWeights(weights);
    saveCustom(sport, weights);
  };

  const editWeight = (stat: string, value: number) => {
    const next = { ...editable(activeWeights), [stat]: value };
    setCustomWeights(next);
    saveCustom(sport, next);
    setChoice("custom");
  };

  const resetWeights = () => {
    setCustomWeights({});
    saveCustom(sport, {});
    if (choice === "custom") setChoice("default");
  };

  const advise = () => {
    setShowAdvice(true);
    setSpots(1);
    setTimeout(() => adviceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  };

  // With fewer than two players there is nothing to compare.
  const adviceVisible = showAdvice && picked.length >= 2;
  const rows = tab === "top" ? top : team;
  const options = scoringOptions(sport);

  return (
    <main>
      <section aria-label="Choose players" className="bg-nav text-white">
        <div className="mx-auto max-w-[1120px] space-y-5 px-4 pb-6 pt-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="font-display text-4xl font-bold uppercase leading-none tracking-[0.02em] sm:text-[44px]">
                Who should I start?
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-[#c9c1e6]">
                {sport === "NFL" ? (
                  <div className="flex items-center gap-1" role="group" aria-label="Week">
                    <button
                      type="button"
                      aria-label="Previous week"
                      disabled={!shownWeek || shownWeek <= 1}
                      onClick={() => setWeek((shownWeek ?? 2) - 1)}
                      className="grid h-8 w-8 place-items-center rounded-full text-xl leading-none hover:bg-white/10 disabled:opacity-30"
                    >
                      ‹
                    </button>
                    <span className="min-w-[64px] text-center font-semibold text-white">
                      {shownWeek ? `Week ${shownWeek}` : "This week"}
                    </span>
                    <button
                      type="button"
                      aria-label="Next week"
                      disabled={!shownWeek || shownWeek >= LAST_WEEK}
                      onClick={() => setWeek((shownWeek ?? 0) + 1)}
                      className="grid h-8 w-8 place-items-center rounded-full text-xl leading-none hover:bg-white/10 disabled:opacity-30"
                    >
                      ›
                    </button>
                    {week !== null && (
                      <button
                        type="button"
                        onClick={() => setWeek(null)}
                        className="ml-1 rounded-md px-2 py-0.5 text-xs font-semibold text-[#c9b8ff] hover:bg-white/10"
                      >
                        Current week
                      </button>
                    )}
                  </div>
                ) : (
                  <span className="font-semibold text-white">Next game</span>
                )}
                <span aria-hidden="true" className="max-sm:hidden">·</span>
                <span className="max-sm:basis-full">Search or pick players below for start/sit advice.</span>
              </div>
            </div>

            <div className="flex flex-wrap items-end gap-3">
              <div role="group" aria-label="Sport" className="flex rounded-[10px] bg-white/10 p-1">
                {SPORTS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={sport === option}
                    onClick={() => chooseSport(option)}
                    className={`h-8 rounded-lg px-3.5 text-sm font-bold ${
                      sport === option ? "bg-surface text-ink" : "text-[#c9c1e6] hover:text-white"
                    }`}
                  >
                    {option}
                  </button>
                ))}
              </div>
              <div>
                <label htmlFor={ids.source} className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-[#b9b0da]">
                  Source
                </label>
                {sportSources.length > 1 ? (
                  <select id={ids.source} value={source} onChange={(e) => setSource(e.target.value)} className={selectClass}>
                    {sportSources.map((option) => (
                      <option key={option.name} value={option.name}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  // One source (Sleeper) for now: a label, not a menu with a single choice.
                  <div id={ids.source} className="flex h-10 items-center rounded-[10px] bg-white/10 px-3 text-sm font-semibold text-white">
                    {sourceLabel}
                  </div>
                )}
              </div>
              <div>
                <label htmlFor={ids.scoring} className="mb-1 block text-[11px] font-semibold uppercase tracking-wider text-[#b9b0da]">
                  Scoring
                </label>
                <select id={ids.scoring} value={choice} onChange={(e) => chooseScoring(e.target.value as ScoringChoice)} className={selectClass}>
                  {options.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                aria-label="Sources and scoring settings"
                aria-expanded={settingsOpen}
                aria-controls="start-settings"
                onClick={() => setSettingsOpen((open) => !open)}
                className={`grid h-10 w-10 place-items-center rounded-[10px] ${
                  settingsOpen ? "bg-accent text-on-accent" : "bg-surface text-ink"
                }`}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
                </svg>
              </button>
            </div>
          </div>

          {settingsOpen && (
            <ScoringSettings
              sport={sport}
              sources={sportSources}
              choice={choice}
              weights={activeWeights}
              onWeight={editWeight}
              onReset={resetWeights}
            />
          )}

          <PlayerSearch sport={sport} pickedKeys={pickedKeys} full={full} onPick={add} />
          <SlotCards
            picked={picked}
            savedKeys={savedKeys}
            advising={adviceLoading && adviceVisible}
            onRemove={remove}
            onToggleSaved={toggleSaved}
            onAdvise={advise}
          />
          {notice && (
            <p role="status" className="text-sm text-[#ffd166]">
              {notice}
            </p>
          )}
        </div>
      </section>

      <div className="mx-auto max-w-[1120px] space-y-6 px-4 pb-14 pt-6">
        {adviceVisible && (
          <div ref={adviceRef} className="scroll-mt-4">
            {adviceError ? (
              <p role="alert" className="rounded-2xl border border-line bg-surface p-5 text-bad shadow-panel">
                {adviceError}
              </p>
            ) : adviceEntries === null ? (
              <p role="status" className="rounded-2xl border border-line bg-surface p-5 text-ink-3 shadow-panel">
                Working out the advice…
              </p>
            ) : (
              <div aria-busy={adviceLoading} className={adviceLoading ? "opacity-60" : ""}>
                <AdvicePanel
                  entries={adviceEntries}
                  sourceLabel={sourceLabel}
                  scoringName={adviceScoring || (scoring?.name ?? "FantasyIQ")}
                  week={adviceWeek}
                  spots={Math.min(spots, Math.max(picked.length - 1, 1))}
                  onSpots={setSpots}
                />
              </div>
            )}
          </div>
        )}

        <section
          ref={listRef}
          aria-label="Players to compare"
          className="scroll-mt-4 overflow-hidden rounded-2xl border border-line bg-surface-2 shadow-panel"
        >
          <div role="tablist" aria-label="Player lists" className="flex gap-1 border-b border-line bg-surface px-3 pt-2">
            {(
              [
                ["top", "Top players"],
                ["team", `My team${saved.length ? ` (${saved.length})` : ""}`],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                onClick={() => setTab(id)}
                className={`-mb-px border-b-[3px] px-3.5 py-2.5 text-sm font-semibold ${
                  tab === id ? "border-accent text-ink" : "border-transparent text-ink-3 hover:text-ink"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === "top" && (
            <div role="group" aria-label="Lineup slot" className="flex flex-wrap gap-1 border-b border-line bg-surface px-3 py-2">
              {SLOTS[sport].map((option) => (
                <button
                  key={option.id}
                  type="button"
                  aria-pressed={slot === option.id}
                  onClick={() => setSlot(option.id)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${
                    slot === option.id ? "bg-accent text-on-accent" : "text-ink-2 hover:bg-surface-2"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          )}

          <div role="tabpanel">
            <ProjectionList
              entries={rows}
              startRank={tab === "top" ? offset + 1 : 1}
              loading={tab === "top" ? topLoading : teamLoading}
              error={tab === "top" ? topError : teamError}
              empty={
                tab === "top"
                  ? "No projections for this slot yet."
                  : "Star players (in the lists or on their card) to build your team. It is saved in this browser until you can link a league."
              }
              pickedKeys={pickedKeys}
              savedKeys={savedKeys}
              onTogglePicked={togglePicked}
              onToggleSaved={toggleSaved}
            />
          </div>

          {tab === "top" && topTotal > 0 && (
            <nav
              aria-label="Pages of players"
              className="flex items-center justify-between gap-3 border-t border-line bg-surface px-4 py-3"
            >
              <button
                type="button"
                onClick={() => goToOffset(Math.max(offset - PAGE_SIZE, 0))}
                disabled={offset === 0 || topLoading}
                className="h-9 rounded-lg border border-line px-3.5 text-sm font-semibold text-ink hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous {PAGE_SIZE}
              </button>
              <span role="status" className="text-sm text-ink-3">
                Showing {Math.min(offset + 1, topTotal)}–{Math.min(offset + top.length, topTotal)} of{" "}
                {topTotal}
              </span>
              <button
                type="button"
                onClick={() => goToOffset(offset + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= topTotal || topLoading}
                className="h-9 rounded-lg border border-line px-3.5 text-sm font-semibold text-ink hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next {PAGE_SIZE}
              </button>
            </nav>
          )}
        </section>
      </div>
    </main>
  );
}
