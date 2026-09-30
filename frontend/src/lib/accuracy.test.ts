import {
  chartRows,
  formatBias,
  formatCorrelation,
  formatMiss,
  orderedSources,
  sourceColor,
  sourceLabel,
  verdict,
} from "./accuracy";
import { makeAccuracyResponse, makeAccuracyTotals } from "@/test/fixtures";

describe("sources", () => {
  it("names the known sources and falls back to the raw name", () => {
    expect(sourceLabel("fantasyiq")).toBe("FantasyIQ model");
    expect(sourceLabel("sleeper")).toBe("Sleeper");
    expect(sourceLabel("yahoo")).toBe("yahoo");
  });

  it("colors by who the source is, never by its order", () => {
    expect(sourceColor("fantasyiq")).toBe("var(--series-model)");
    expect(sourceColor("sleeper")).toBe("var(--series-other)");
    expect(sourceColor("fantasyiq")).toBe(sourceColor("fantasyiq"));
  });

  it("puts our model first, then the others alphabetically", () => {
    expect(orderedSources(["sleeper", "fantasyiq"])).toEqual(["fantasyiq", "sleeper"]);
    expect(orderedSources(["yahoo", "sleeper", "fantasyiq"])).toEqual(["fantasyiq", "sleeper", "yahoo"]);
  });
});

describe("formatting", () => {
  it("shows points with a decimal and a dash for nothing", () => {
    expect(formatMiss(4.46)).toBe("4.5");
    expect(formatMiss(null)).toBe("—");
    expect(formatMiss(undefined)).toBe("—");
    expect(formatCorrelation(0.6234)).toBe("0.62");
    expect(formatCorrelation(null)).toBe("—");
  });

  it("signs a bias and calls a negligible one zero", () => {
    expect(formatBias(1.24)).toBe("+1.2");
    expect(formatBias(-0.44)).toBe("−0.4");
    expect(formatBias(0.02)).toBe("0.0");
  });
});

describe("chartRows", () => {
  it("makes one row per week with each source's miss under its name", () => {
    const rows = chartRows(makeAccuracyResponse());

    expect(rows).toEqual([
      { key: "2026-04", label: "Week 4", n: 120, fantasyiq: 4.6, sleeper: 5.1 },
      { key: "2026-05", label: "Week 5", n: 120, fantasyiq: 4.2, sleeper: 4.9 },
    ]);
  });
});

describe("verdict", () => {
  it("says who is closer, and by how much, when there is enough data", () => {
    const result = verdict(makeAccuracyResponse());

    expect(result.kind).toBe("closer");
    expect(result.text).toBe(
      "FantasyIQ model is closer: it misses by 4.4 points on average, 0.6 fewer than Sleeper.",
    );
  });

  it("names the other source when it is the closer one", () => {
    const report = makeAccuracyResponse({
      overall: {
        fantasyiq: makeAccuracyTotals({ mae: 5.5 }),
        sleeper: makeAccuracyTotals({ mae: 4.5 }),
      },
    });

    expect(verdict(report).text).toMatch(/^Sleeper is closer: it misses by 4\.5 points/);
  });

  it("calls a dead heat a tie rather than naming a winner", () => {
    const report = makeAccuracyResponse({
      overall: {
        fantasyiq: makeAccuracyTotals({ mae: 4.5 }),
        sleeper: makeAccuracyTotals({ mae: 4.52 }),
      },
    });

    expect(verdict(report).kind).toBe("tie");
  });

  it("refuses to pick a winner from too little data", () => {
    const result = verdict(makeAccuracyResponse({ compared: 12, enough_data: false }));

    expect(result.kind).toBe("thin");
    expect(result.text).toMatch(/Only 12 player-games so far/);
  });

  it("explains an empty report", () => {
    const result = verdict(makeAccuracyResponse({ compared: 0, enough_data: false, overall: {} }));

    expect(result.kind).toBe("empty");
    expect(result.text).toMatch(/No finished games have saved projections/);
  });

  it("has nothing to compare with a single source", () => {
    const report = makeAccuracyResponse({
      sources: ["sleeper"],
      overall: { sleeper: makeAccuracyTotals() },
    });

    expect(verdict(report).text).toMatch(/nothing to compare/);
  });
});
