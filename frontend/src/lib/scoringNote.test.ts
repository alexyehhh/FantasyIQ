import type { ScoringConfig } from "./api";
import { describeScoring } from "./scoringNote";

const CONFIG: ScoringConfig = {
  name: "Test league",
  sport: "NFL",
  player_weights: {
    passing_yards: 0.04,
    interceptions: -2,
    receptions: 1,
    kick_return_touchdowns: 6,
    extra_points_made: 1,
    extra_points_missed: -1,
  },
  field_goal_made: [
    { min: 0, max: 39, points: 3 },
    { min: 40, max: 49, points: 4 },
    { min: 50, max: null, points: 5 },
  ],
  field_goal_missed: [
    { min: 0, max: 39, points: -3 },
    { min: 50, max: null, points: -1 },
  ],
  defense_weights: { sacks: 1, interceptions: 2 },
  points_allowed: [
    { min: 0, max: 0, points: 10 },
    { min: 1, max: 6, points: 7 },
    { min: 35, max: null, points: -4 },
  ],
};

describe("describeScoring", () => {
  it("lists a player's weights with a real minus sign, leaving out kicker stats", () => {
    const text = describeScoring(CONFIG, "player");

    expect(text).toBe(
      "FPTS uses Test league scoring: Passing yards +0.04, Interceptions −2, Receptions +1, " +
        "Kick return TDs +6.",
    );
  });

  it("describes a kicker by distance bracket, then extra points", () => {
    const text = describeScoring(CONFIG, "kicker");

    expect(text).toContain("Field goals made 0–39 yds +3, 40–49 yds +4, 50+ yds +5");
    expect(text).toContain("missed 0–39 yds −3, 50+ yds −1");
    expect(text).toContain("Extra points made +1, Extra points missed −1");
    expect(text).not.toContain("Passing yards");
  });

  it("describes a defense by weight, then points allowed", () => {
    const text = describeScoring(CONFIG, "defense");

    expect(text).toBe(
      "FPTS uses Test league scoring: Sacks +1, Interceptions +2, " +
        "Points allowed 0 +10, 1–6 +7, 35+ −4.",
    );
  });

  it("writes a zero-point bracket as a plain 0", () => {
    const config: ScoringConfig = {
      ...CONFIG,
      points_allowed: [{ min: 21, max: 27, points: 0 }],
    };

    expect(describeScoring(config, "defense")).toContain("Points allowed 21–27 0");
  });

  it("says nothing about brackets a league doesn't use", () => {
    const flat: ScoringConfig = {
      ...CONFIG,
      field_goal_made: [],
      field_goal_missed: [],
      player_weights: { field_goals_made: 3 },
    };

    expect(describeScoring(flat, "kicker")).toBe(
      "FPTS uses Test league scoring: Field goals made +3.",
    );
  });
});
