import {
  NBA_POSITION_FILTERS,
  NFL_POSITION_FILTERS,
  displayPosition,
  isPunter,
  positionFiltersFor,
} from "./positions";

describe("NFL position filters", () => {
  it("offers the fantasy roster slots in order", () => {
    expect(NFL_POSITION_FILTERS.map((filter) => filter.label)).toEqual([
      "QB",
      "RB",
      "WR",
      "TE",
      "W/R/T",
      "K",
      "DEF",
    ]);
  });

  it("makes W/R/T match running backs, receivers and tight ends", () => {
    const flex = NFL_POSITION_FILTERS.find((filter) => filter.label === "W/R/T")!;

    expect(flex.positions).toEqual(expect.arrayContaining(["RB", "WR", "TE"]));
    expect(flex.positions).not.toContain("QB");
  });

  it("matches kickers by ESPN's code, PK", () => {
    expect(NFL_POSITION_FILTERS.find((filter) => filter.label === "K")!.positions).toEqual(["PK"]);
  });

  it("counts fullbacks as running backs, as Yahoo does", () => {
    expect(NFL_POSITION_FILTERS.find((filter) => filter.label === "RB")!.positions).toContain("FB");
  });

  it("makes DEF selectable, and lists team defenses rather than players", () => {
    const def = NFL_POSITION_FILTERS.find((filter) => filter.label === "DEF")!;

    expect(def.defense).toBe(true);
    expect(def.unavailable).toBeUndefined();
    expect(def.positions).toEqual([]);
  });

  it("lists players for every other filter", () => {
    for (const filter of NFL_POSITION_FILTERS.filter((f) => f.label !== "DEF")) {
      expect(filter.unavailable).toBeUndefined();
      expect(filter.defense).toBeUndefined();
      expect(filter.positions.length).toBeGreaterThan(0);
    }
  });
});

describe("NBA position filters", () => {
  it("offers G, F, C and Util", () => {
    expect(NBA_POSITION_FILTERS.map((filter) => filter.label)).toEqual(["G", "F", "C", "Util"]);
  });

  it("folds ESPN's rarer specific positions into G and F", () => {
    const byLabel = Object.fromEntries(NBA_POSITION_FILTERS.map((f) => [f.label, f.positions]));

    expect(byLabel.G).toEqual(expect.arrayContaining(["G", "PG", "SG"]));
    expect(byLabel.F).toEqual(expect.arrayContaining(["F", "SF", "PF"]));
    expect(byLabel.C).toEqual(["C"]);
  });

  it("makes Util match every player, and leaves every button selectable", () => {
    expect(NBA_POSITION_FILTERS.find((f) => f.label === "Util")!.positions).toEqual([]);
    expect(NBA_POSITION_FILTERS.every((filter) => filter.unavailable === undefined)).toBe(true);
  });

  it("picks the filters for a sport", () => {
    expect(positionFiltersFor("NFL")).toBe(NFL_POSITION_FILTERS);
    expect(positionFiltersFor("NBA")).toBe(NBA_POSITION_FILTERS);
  });
});

describe("displayPosition", () => {
  it("writes ESPN's PK as K and leaves everything else alone", () => {
    expect(displayPosition("PK")).toBe("K");
    expect(displayPosition("QB")).toBe("QB");
    expect(displayPosition(null)).toBeNull();
  });

  it("recognizes punters, who have no fantasy points, but not kickers", () => {
    expect(isPunter("P")).toBe(true);
    expect(isPunter("PK")).toBe(false);
    expect(isPunter("WR")).toBe(false);
    expect(isPunter(null)).toBe(false);
  });
});
