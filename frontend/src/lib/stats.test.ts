import { makeEntry } from "@/test/fixtures";
import {
  FPTS,
  NEGATIVE_STATS,
  STAT_LABELS,
  NBA_LOG_COLUMNS,
  NFL_LOG_COLUMNS,
  average,
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

  it("marks kickers and punters as untracked, since no kicking stats are stored", () => {
    expect(profileFor("NFL", "PK").tracked).toBe(false);
    expect(profileFor("NFL", "P").tracked).toBe(false);
    expect(profileFor("NFL", "PK").tiles).toEqual([]);
  });

  it("tracks every other position", () => {
    for (const position of ["QB", "RB", "WR", "TE", "LB", null]) {
      expect(profileFor("NFL", position).tracked).toBe(true);
    }
    expect(profileFor("NBA", "G").tracked).toBe(true);
  });

  it("puts fantasy points first in every profile's rows", () => {
    for (const position of ["QB", "RB", "WR", "PK"]) {
      expect(profileFor("NFL", position).rows[0]).toBe(FPTS);
    }
    expect(profileFor("NBA", "G").rows[0]).toBe(FPTS);
  });

  it("only references stats that have a label", () => {
    for (const profile of [profileFor("NBA", "G"), profileFor("NFL", "QB"), profileFor("NFL", "K")]) {
      for (const key of [...profile.tiles, ...profile.rows]) {
        expect(STAT_LABELS[key]).toBeDefined();
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

    expect(statValue(entry, "points", "NBA")).toBe(12);
    expect(statValue(entry, "rebounds", "NBA")).toBe(0);
  });

  it("derives fantasy points from the stat line for the player's sport", () => {
    const entry = makeEntry({ stats: { points: 10, assists: 2 } });

    expect(statValue(entry, FPTS, "NBA")).toBe(13);
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
