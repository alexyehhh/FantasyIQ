import {
  formatBias,
  formatMiss,
  gameMiss,
  orderedSources,
  sourceColor,
  sourceLabel,
  summarize,
} from "./accuracy";
import type { AccuracyPlayerGame } from "./api";

const game = (actual: number | null, projected: Record<string, number>): AccuracyPlayerGame => ({
  game_id: 1,
  player_id: 7,
  player_name: "Aaron Rodgers",
  position: "QB",
  team: "PIT",
  opponent: "CLE",
  home: false,
  season: "2026",
  week: 4,
  start_time: "2026-10-02T00:15:00",
  played: actual !== null,
  actual,
  projected,
});

describe("sources", () => {
  it("names the known sources and falls back to the raw name", () => {
    expect(sourceLabel("fantasyiq")).toBe("FantasyIQ model");
    expect(sourceLabel("sleeper")).toBe("Sleeper");
    expect(sourceLabel("yahoo")).toBe("yahoo");
  });

  it("colors by who the source is, never by its order", () => {
    expect(sourceColor("fantasyiq")).toBe("var(--series-model)");
    expect(sourceColor("sleeper")).toBe("var(--series-other)");
  });

  it("puts our model first, then the others alphabetically", () => {
    expect(orderedSources(["yahoo", "sleeper", "fantasyiq"])).toEqual(["fantasyiq", "sleeper", "yahoo"]);
  });
});

describe("formatting", () => {
  it("shows points with a decimal and a dash for nothing", () => {
    expect(formatMiss(4.46)).toBe("4.5");
    expect(formatMiss(null)).toBe("—");
  });

  it("signs a bias", () => {
    expect(formatBias(1.24)).toBe("+1.2");
    expect(formatBias(-0.4)).toBe("−0.4");
    expect(formatBias(0.01)).toBe("0.0");
  });
});

describe("gameMiss", () => {
  it("is projected minus actual, null without a result or a projection", () => {
    expect(gameMiss(game(20, { sleeper: 13.5 }), "sleeper")).toBeCloseTo(-6.5);
    expect(gameMiss(game(null, { sleeper: 13.5 }), "sleeper")).toBeNull();
    expect(gameMiss(game(20, {}), "sleeper")).toBeNull();
  });
});

describe("summarize", () => {
  it("averages each source's miss and names the closer one", () => {
    const summary = summarize([
      game(20, { fantasyiq: 15, sleeper: 12 }), // misses -5, -8
      game(10, { fantasyiq: 12, sleeper: 16 }), // misses +2, +6
    ]);

    expect(summary.n).toBe(2);
    const [model, sleeper] = summary.averages;
    expect(model).toMatchObject({ source: "fantasyiq", mae: 3.5, bias: -1.5 });
    expect(sleeper).toMatchObject({ source: "sleeper", mae: 7, bias: -1 });
    expect(summary.best).toBe("fantasyiq");
  });

  it("skips games the player missed and games a source didn't project", () => {
    const summary = summarize([
      game(null, { fantasyiq: 15, sleeper: 12 }),
      game(10, { fantasyiq: 12 }),
      game(10, { fantasyiq: 11, sleeper: 9 }),
    ]);

    expect(summary.n).toBe(1);
    expect(summary.averages.map((a) => a.mae)).toEqual([1, 1]);
    expect(summary.best).toBeNull(); // a tie
  });

  it("has nothing to say without games", () => {
    expect(summarize([])).toEqual({ n: 0, averages: [], best: null });
  });
});
