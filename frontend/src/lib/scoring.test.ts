import { DEFAULT_SCORING, fantasyPoints } from "./scoring";

describe("fantasyPoints", () => {
  it("scores an NBA stat line with the default weights", () => {
    const stats = { points: 30, rebounds: 10, assists: 5, steals: 2, blocks: 1, turnovers: 3 };

    // 30 + 12 + 7.5 + 6 + 3 - 3
    expect(fantasyPoints(stats, DEFAULT_SCORING.NBA.weights)).toBe(55.5);
  });

  it("scores an NFL stat line with PPR weights", () => {
    const stats = {
      passing_yards: 300,
      passing_touchdowns: 2,
      interceptions: 1,
      rushing_yards: 20,
      receptions: 1,
      receiving_yards: 10,
    };

    // 12 + 8 - 2 + 2 + 1 + 1
    expect(fantasyPoints(stats, DEFAULT_SCORING.NFL.weights)).toBe(22);
  });

  it("treats stats missing from the line as zero and ignores stats with no weight", () => {
    expect(fantasyPoints({ points: 10, minutes: 40 }, DEFAULT_SCORING.NBA.weights)).toBe(10);
  });

  it("rounds to one decimal place", () => {
    expect(fantasyPoints({ passing_yards: 251 }, DEFAULT_SCORING.NFL.weights)).toBe(10);
    expect(fantasyPoints({ rushing_yards: 17 }, DEFAULT_SCORING.NFL.weights)).toBe(1.7);
  });

  it("lets a league's own weights replace the defaults", () => {
    expect(fantasyPoints({ receptions: 6 }, { receptions: 0.5 })).toBe(3);
  });
});
