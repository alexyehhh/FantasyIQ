import { makeEntry } from "@/test/fixtures";
import {
  DEFENSE_NEGATIVE_STATS,
  FPTS,
  KICKS,
  NEGATIVE_STATS,
  STAT_LABELS,
  NBA_LOG_COLUMNS,
  NFL_LOG_COLUMNS,
  average,
  formatKicks,
  formatStat,
  profileFor,
  statValue,
} from "./stats";

describe("profileFor", () => {
  it("uses one profile for every NBA position", () => {
    expect(profileFor("NBA", "G").defaultStat).toBe("points");
    expect(profileFor("NBA", null)).toBe(profileFor("NBA", "C"));
  });

  it.each([
    ["QB", "passing_yards"],
    ["RB", "rushing_yards"],
    ["FB", "rushing_yards"],
    ["WR", "receiving_yards"],
    ["TE", "receiving_yards"],
  ])("defaults %s to %s", (position, stat) => {
    expect(profileFor("NFL", position).defaultStat).toBe(stat);
  });

  it("falls back to a generic profile for positions the stored stats don't describe", () => {
    expect(profileFor("NFL", "LB").rows).toContain(FPTS);
    expect(profileFor("NFL", null).tiles).toHaveLength(4);
  });

  it("tracks kickers by field goals and extra points, and lists each kick in their game log", () => {
    const kicker = profileFor("NFL", "PK");

    expect(kicker.tracked).toBe(true);
    expect(kicker.tiles).toContain("field_goals_made");
    expect(kicker.logColumns.map((column) => column.key)).toContain(KICKS);
    expect(kicker.scoringKind).toBe("kicker");
  });

  it("leaves punters untracked, since no punting stats are stored", () => {
    const punter = profileFor("NFL", "P");

    expect(punter.tracked).toBe(false);
    expect(punter.tiles).toEqual([]);
    expect(punter.logColumns).toEqual([]);
    expect(punter.untrackedLabel).toBe("Punting");
  });

  it("gives a team defense its own profile, where fewer points and yards allowed are better", () => {
    const defense = profileFor("NFL", "DEF");

    expect(defense.scoringKind).toBe("defense");
    expect(defense.tiles).toEqual(["sacks", "interceptions", "points_allowed", "yards_allowed"]);
    expect(defense.negativeStats).toBe(DEFENSE_NEGATIVE_STATS);
    // A defense's interceptions are good news, unlike a quarterback's.
    expect(defense.negativeStats.has("interceptions")).toBe(false);
    expect(profileFor("NFL", "QB").negativeStats.has("interceptions")).toBe(true);
  });

  it("tracks every other position", () => {
    for (const position of ["QB", "RB", "WR", "TE", "PK", "DEF", "LB", null]) {
      expect(profileFor("NFL", position).tracked).toBe(true);
    }
    expect(profileFor("NBA", "G").tracked).toBe(true);
  });

  it("puts fantasy points first in every profile's rows", () => {
    for (const position of ["QB", "RB", "WR", "PK", "DEF"]) {
      expect(profileFor("NFL", position).rows[0]).toBe(FPTS);
    }
    expect(profileFor("NBA", "G").rows[0]).toBe(FPTS);
  });

  it("only references stats that have a label", () => {
    const profiles = [
      profileFor("NBA", "G"),
      profileFor("NFL", "QB"),
      profileFor("NFL", "PK"),
      profileFor("NFL", "DEF"),
    ];
    for (const profile of profiles) {
      for (const key of [...profile.tiles, ...profile.rows]) {
        expect(STAT_LABELS[key]).toBeDefined();
      }
      for (const column of profile.logColumns) {
        expect(STAT_LABELS[column.key]).toBeDefined();
      }
    }
    for (const column of [...NBA_LOG_COLUMNS, ...NFL_LOG_COLUMNS]) {
      expect(STAT_LABELS[column.key]).toBeDefined();
    }
  });
});

describe("statValue", () => {
  it("reads a raw stat, defaulting to zero when the line lacks it", () => {
    const entry = makeEntry({ stats: { points: 12 } });

    expect(statValue(entry, "points")).toBe(12);
    expect(statValue(entry, "rebounds")).toBe(0);
  });

  it("takes fantasy points from the backend rather than working them out", () => {
    const entry = makeEntry({ stats: { points: 10, assists: 2 }, fantasy_points: 42.5 });

    expect(statValue(entry, FPTS)).toBe(42.5);
  });
});

describe("formatKicks", () => {
  it("lists distances in order, marking misses and blocks", () => {
    expect(
      formatKicks([
        { distance: 24, result: "made" },
        { distance: 43, result: "missed" },
        { distance: 49, result: "blocked" },
      ]),
    ).toBe("24, 43 (miss), 49 (blocked)");
  });

  it("shows a dash when there were no attempts", () => {
    expect(formatKicks([])).toBe("—");
    expect(formatKicks(undefined)).toBe("—");
  });
});

describe("average and formatStat", () => {
  it("averages, treating an empty list as zero", () => {
    expect(average([2, 4, 9])).toBe(5);
    expect(average([])).toBe(0);
  });

  it("keeps whole numbers whole and rounds the rest to one decimal", () => {
    expect(formatStat(28)).toBe("28");
    expect(formatStat(27.63)).toBe("27.6");
    expect(formatStat(4.96)).toBe("5");
    expect(formatStat(0)).toBe("0");
  });
});

it("flags turnovers, interceptions and fumbles as stats where lower is better", () => {
  expect([...NEGATIVE_STATS].sort()).toEqual(["fumbles_lost", "interceptions", "turnovers"]);
});
