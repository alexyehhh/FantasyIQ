import { makeProjectionEntry as entry } from "@/test/fixtures";
import type { ScoringConfig } from "./api";
import {
  buildAdvice,
  edgeFor,
  explain,
  isLocked,
  joinNames,
  buildPageQuery,
  loadLastQuery,
  loadMyTeam,
  matchupLine,
  parsePageState,
  saveLastQuery,
  rankEntries,
  type PageState,
  saveMyTeam,
  scoringFor,
  splitByKind,
  winProbability,
} from "./startSit";

const BASE: ScoringConfig = {
  name: "FantasyIQ standard (PPR)",
  sport: "NFL",
  player_weights: { receptions: 1, passing_yards: 0.04, receiving_yards: 0.1 },
  field_goal_made: [{ min: 0, max: 39, points: 3 }],
  field_goal_missed: [],
  defense_weights: { sacks: 1 },
  points_allowed: [],
};

describe("winProbability", () => {
  it("is even for equal projections and favors the higher one", () => {
    expect(winProbability({ fantasy_points: 15, std: 6 }, { fantasy_points: 15, std: 6 })).toBeCloseTo(0.5);
    const ahead = winProbability({ fantasy_points: 20, std: 6 }, { fantasy_points: 15, std: 6 });
    expect(ahead).toBeGreaterThan(0.6);
    expect(winProbability({ fantasy_points: 15, std: 6 }, { fantasy_points: 20, std: 6 })).toBeCloseTo(1 - ahead);
  });

  it("matches the normal distribution", () => {
    // gap 8.49 over a combined spread of 8.49 is one standard deviation: 84.1%
    const p = winProbability({ fantasy_points: 8.485, std: 6 }, { fantasy_points: 0, std: 6 });
    expect(p).toBeCloseTo(0.8413, 3);
  });

  it("treats no spread as certain", () => {
    expect(winProbability({ fantasy_points: 2, std: 0 }, { fantasy_points: 1, std: null })).toBe(1);
    expect(winProbability({ fantasy_points: 1, std: 0 }, { fantasy_points: 1, std: 0 })).toBe(0.5);
  });

  it("gives a wider spread a better chance from behind", () => {
    const tight = winProbability({ fantasy_points: 16, std: 3 }, { fantasy_points: 18, std: 3 });
    const wide = winProbability({ fantasy_points: 16, std: 12 }, { fantasy_points: 18, std: 3 });
    expect(wide).toBeGreaterThan(tight);
  });
});

describe("edgeFor", () => {
  it("calls 70%+ clear, 55-70% a lean and the rest a toss-up, whichever side leads", () => {
    expect(edgeFor(0.72)).toBe("clear");
    expect(edgeFor(0.3)).toBe("clear");
    expect(edgeFor(0.6)).toBe("lean");
    expect(edgeFor(0.52)).toBe("toss-up");
    expect(edgeFor(0.5)).toBe("toss-up");
  });
});

describe("rankEntries and buildAdvice", () => {
  const a = entry({ id: 1, name: "A", fantasy_points: 12 });
  const b = entry({ id: 2, name: "B", fantasy_points: 20 });
  const none = entry({ id: 3, name: "None", fantasy_points: null, status: "unavailable" });
  const c = entry({ id: 4, name: "C", fantasy_points: 16 });

  it("ranks by points with anyone without a number last", () => {
    expect(rankEntries([a, none, b, c]).map((e) => e.name)).toEqual(["B", "C", "A", "None"]);
  });

  it("starts the top N and measures the chance of the cutoff", () => {
    const one = buildAdvice([a, none, b, c], 1);
    expect(one.starters.map((e) => e.name)).toEqual(["B"]);
    expect(one.cutoffChance).toBeCloseTo(winProbability(b, c));
    expect(one.edge).not.toBeNull();

    const two = buildAdvice([a, b, c], 2);
    expect(two.starters.map((e) => e.name)).toEqual(["B", "C"]);
    expect(two.cutoffChance).toBeCloseTo(winProbability(c, a));
  });

  it("has no cutoff when there is only one player to start", () => {
    const only = buildAdvice([a], 1);
    expect(only.starters).toEqual([a]);
    expect(only.cutoffChance).toBeNull();
    expect(only.edge).toBeNull();
  });

  it("copes with nobody having a projection", () => {
    expect(buildAdvice([none], 1).starters).toEqual([]);
  });
});

describe("joinNames", () => {
  it("reads naturally", () => {
    expect(joinNames(["A"])).toBe("A");
    expect(joinNames(["A", "B"])).toBe("A and B");
    expect(joinNames(["A", "B", "C"])).toBe("A, B and C");
  });
});

describe("explain", () => {
  const top = entry({ id: 1, name: "Top", fantasy_points: 20, std: 8 });
  const second = entry({ id: 2, name: "Second", fantasy_points: 15, std: 8 });
  const ranked = [top, second];

  it("says how far ahead or behind, and by whom", () => {
    expect(explain(top, ranked)[0].text).toBe("5.0 points ahead of Second.");
    expect(explain(second, ranked)[0].text).toBe("5.0 points behind Top.");
  });

  it("leads with injury warnings", () => {
    const hurt = entry({ id: 3, name: "Hurt", fantasy_points: 21, injury_status: "Questionable" });
    const reasons = explain(hurt, [hurt, second]);
    expect(reasons[0].tone).toBe("warn");
    expect(reasons[0].text).toContain("Questionable");
  });

  it("explains players who are out, on a bye or without a projection", () => {
    expect(explain(entry({ status: "out", injury_status: "Out", fantasy_points: 0 }), ranked)[0].text).toContain("Ruled out");
    expect(explain(entry({ status: "no_game", fantasy_points: null, notes: ["No game this week (bye week)."] }), ranked)[0].text).toContain("bye");
    expect(explain(entry({ status: "unavailable", fantasy_points: null }), ranked)[0].tone).toBe("warn");
  });

  it("calls out a much wider or narrower range than the others", () => {
    const boom = entry({ id: 5, name: "Boom", fantasy_points: 18, std: 14 });
    const steady = entry({ id: 6, name: "Steady", fantasy_points: 18, std: 4 });
    const others = [boom, steady, second];
    expect(explain(boom, others).some((r) => r.text.includes("Bigger swings"))).toBe(true);
    expect(explain(steady, others).some((r) => r.text.includes("Steadier"))).toBe(true);
  });

  it("reports stats a source doesn't project and never gives more than four reasons", () => {
    const busy = entry({
      fantasy_points: 20,
      std: 20,
      injury_status: "Doubtful",
      unprojected_stats: ["fourth_down_stops"],
      approximate: true,
    });
    const reasons = explain(busy, [busy, second]);
    expect(reasons.length).toBeLessThanOrEqual(4);
    expect(reasons.map((r) => r.text).join(" ")).toContain("fourth down stops");
  });
});

describe("scoringFor", () => {
  it("sends nothing for the default", () => {
    expect(scoringFor("default", BASE, {})).toBeNull();
    expect(scoringFor("half", null, {})).toBeNull(); // the default hasn't loaded
  });

  it("changes only the reception weight for half-PPR and standard", () => {
    const half = scoringFor("half", BASE, {});
    expect(half?.name).toBe("Half-PPR");
    expect(half?.player_weights).toEqual({ ...BASE.player_weights, receptions: 0.5 });
    expect(half?.field_goal_made).toEqual(BASE.field_goal_made);
    expect(scoringFor("standard", BASE, {})?.player_weights.receptions).toBe(0);
  });

  it("applies custom weights over the default", () => {
    const custom = scoringFor("custom", BASE, { receptions: 2, passing_yards: 0.05 });
    expect(custom?.name).toBe("Custom");
    expect(custom?.player_weights).toEqual({ receptions: 2, passing_yards: 0.05, receiving_yards: 0.1 });
  });
});

describe("selection helpers", () => {
  it("splits candidates by kind", () => {
    expect(splitByKind([{ kind: "player", id: 1 }, { kind: "defense", id: 9 }, { kind: "player", id: 2 }])).toEqual({
      playerIds: [1, 2],
      defenseIds: [9],
    });
  });
});

describe("saved roster", () => {
  beforeEach(() => window.localStorage.clear());

  it("round-trips per sport and ignores junk", () => {
    saveMyTeam("NFL", [{ kind: "player", id: 3 }]);
    expect(loadMyTeam("NFL")).toEqual([{ kind: "player", id: 3 }]);
    expect(loadMyTeam("NBA")).toEqual([]);

    window.localStorage.setItem("fantasyiq.myTeam.NBA", JSON.stringify([{ kind: "x", id: 1 }, { kind: "player", id: "no" }, { kind: "defense", id: 4 }]));
    expect(loadMyTeam("NBA")).toEqual([{ kind: "defense", id: 4 }]);
    window.localStorage.setItem("fantasyiq.myTeam.NBA", "not json");
    expect(loadMyTeam("NBA")).toEqual([]);
  });
});

describe("matchupLine", () => {
  const seattle = { abbreviation: "SEA" };
  const washington = { abbreviation: "WSH" };

  it("puts the opponent right after the team, with @ away and vs at home", () => {
    const away = entry({ position: "WR", team: seattle as never, game: { ...entry().game!, is_home: false, opponent: washington as never } });
    const home = entry({ position: "RB", team: { abbreviation: "DET" } as never, game: { ...entry().game!, is_home: true, opponent: { abbreviation: "NYJ" } as never } });

    expect(matchupLine(away)).toBe("WR · SEA @ WSH");
    expect(matchupLine(home)).toBe("RB · DET vs NYJ");
  });

  it("is just position and team without a game, and shows kickers as K", () => {
    expect(matchupLine(entry({ position: "PK", team: seattle as never, game: null }))).toBe("K · SEA");
    expect(matchupLine(entry({ position: null, team: null, game: null }))).toBe("–");
  });
});

describe("players whose game has started", () => {
  const scheduled = entry().game!;
  const over = { ...scheduled, status: "final" as const };
  const live = { ...scheduled, status: "in_progress" as const };
  const open = entry({ id: 1, name: "Open", fantasy_points: 15 });
  const openToo = entry({ id: 2, name: "Also Open", fantasy_points: 12 });
  const played = entry({ id: 3, name: "Played", fantasy_points: 30, game: over });

  it("knows who is locked", () => {
    expect(isLocked(open)).toBe(false);
    expect(isLocked(played)).toBe(true);
    expect(isLocked(entry({ game: live }))).toBe(true);
    expect(isLocked(entry({ game: null }))).toBe(false);
  });

  it("keeps them out of the starters however high they scored, and still lists them", () => {
    const advice = buildAdvice([played, open, openToo], 1);

    expect(advice.starters.map((e) => e.name)).toEqual(["Open"]);
    expect(advice.sitters.map((e) => e.name)).toEqual(["Also Open"]);
    expect(advice.locked.map((e) => e.name)).toEqual(["Played"]);
    expect(advice.ranked.map((e) => e.name)).toEqual(["Open", "Also Open", "Played"]);
  });

  it("measures the cutoff between the players who can still be started", () => {
    const advice = buildAdvice([played, open, openToo], 1);

    expect(advice.cutoffChance).toBeCloseTo(winProbability(open, openToo));
  });

  it("has nobody to start when every game has started, and no cutoff", () => {
    const advice = buildAdvice([played, entry({ id: 4, name: "Live", fantasy_points: 9, game: live })], 1);

    expect(advice.starters).toEqual([]);
    expect(advice.locked).toHaveLength(2);
    expect(advice.cutoffChance).toBeNull();
  });

  it("never asks for more starting spots than there are players to start", () => {
    expect(buildAdvice([played, open, openToo], 5).starters).toHaveLength(1);
    expect(buildAdvice([played, open], 3).starters.map((e) => e.name)).toEqual(["Open"]);
  });

  it("explains a locked player first and only that, and ignores them when explaining others", () => {
    const reasons = explain(played, [open, played]);
    expect(reasons).toHaveLength(1);
    expect(reasons[0].tone).toBe("warn");
    expect(reasons[0].text).toContain("Game over");
    expect(explain(entry({ id: 5, fantasy_points: 20, game: live }), [])[0].text).toContain("Game in progress");

    const forOpen = explain(open, [open, played, openToo]).map((r) => r.text).join(" ");
    expect(forOpen).toContain("3.0 points ahead of Also Open");
    expect(forOpen).not.toContain("Played");
  });
});

describe("page state in the address", () => {
  const base: PageState = { sport: "NFL", slot: "FLEX", week: null, scoring: "default", picks: [], advice: false };

  it("writes nothing for the defaults", () => {
    expect(buildPageQuery(base)).toBe("");
    expect(buildPageQuery({ ...base, sport: "NBA", slot: "UTIL" })).toBe("sport=NBA");
  });

  it("writes only what differs, with picks in order", () => {
    const query = buildPageQuery({
      sport: "NFL",
      slot: "WR",
      week: 5,
      scoring: "half",
      picks: [{ kind: "player", id: 1384 }, { kind: "defense", id: 67 }, { kind: "player", id: 7 }],
      advice: true,
    });

    expect(query).toBe("slot=WR&week=5&scoring=half&picks=p1384,d67,p7&advice=1");
  });

  it("only writes advice when there is something to compare", () => {
    expect(buildPageQuery({ ...base, picks: [{ kind: "player", id: 1 }], advice: true })).toBe("picks=p1");
  });

  it("reads back what it wrote", () => {
    const state: PageState = {
      sport: "NFL",
      slot: "SUPERFLEX",
      week: 12,
      scoring: "standard",
      picks: [{ kind: "defense", id: 3 }, { kind: "player", id: 9 }],
      advice: true,
    };

    // NFL is the default sport, so it isn't written and reads back as absent
    const { sport: _sport, ...rest } = state;
    expect(parsePageState(`?${buildPageQuery(state)}`)).toEqual(rest);
    const nba: PageState = { ...state, sport: "NBA", slot: "G", week: null, scoring: "custom", picks: [{ kind: "player", id: 2 }, { kind: "player", id: 8 }] };
    const { week: _week, ...nbaRest } = nba; // no week is written for the current one
    expect(parsePageState(`?${buildPageQuery(nba)}`)).toEqual(nbaRest);
  });

  it("drops anything invalid instead of failing", () => {
    expect(
      parsePageState("?sport=MLB&slot=NOPE&week=99&scoring=free&picks=x1,p0,pabc,p5,p5,d,q9&advice=1"),
    ).toEqual({ picks: [{ kind: "player", id: 5 }] });
    expect(parsePageState("")).toEqual({});
  });

  it("checks slots, weeks, scoring and defenses against the sport", () => {
    expect(parsePageState("?sport=NBA&slot=WR&week=3&scoring=half&picks=d4,p6")).toEqual({
      sport: "NBA",
      picks: [{ kind: "player", id: 6 }],
    });
    expect(parsePageState("?sport=NBA&slot=g&scoring=custom")).toEqual({
      sport: "NBA",
      slot: "G",
      scoring: "custom",
    });
  });

  it("keeps at most as many picks as can be compared", () => {
    const picks = Array.from({ length: 9 }, (_, i) => `p${i + 1}`).join(",");

    expect(parsePageState(`?picks=${picks}`).picks).toHaveLength(5);
  });

  it("remembers the last visit in this browser", () => {
    window.localStorage.clear();
    expect(loadLastQuery()).toBe("");

    saveLastQuery("slot=WR&picks=p1,p2");

    expect(loadLastQuery()).toBe("slot=WR&picks=p1,p2");
  });
});
