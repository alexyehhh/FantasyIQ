import { formatGameDate, formatGameDateTime, formatGameTime } from "./format";

describe("game dates and times", () => {
  it("shows the date in US Pacific time, not UTC", () => {
    // 00:15 UTC on the 15th is still the evening of the 14th on the west coast.
    expect(formatGameDate("2026-09-15T00:15:00Z")).toBe("Sep 14");
  });

  it("shows a kickoff in Pacific time without labelling the zone", () => {
    expect(formatGameTime("2026-09-27T17:00:00Z")).toBe("10:00 AM");
    expect(formatGameDateTime("2026-09-27T17:00:00Z")).toBe("Sun, Sep 27 · 10:00 AM");
  });

  it("rolls a late-evening East coast game back to the previous evening", () => {
    // 8:15 PM Eastern on Oct 21 is 5:15 PM Pacific.
    expect(formatGameDateTime("2026-10-22T00:15:00Z")).toBe("Wed, Oct 21 · 5:15 PM");
  });

  it("follows daylight saving time", () => {
    // Standard time in December: UTC-8.
    expect(formatGameDateTime("2026-12-27T18:00:00Z")).toBe("Sun, Dec 27 · 10:00 AM");
  });
});
