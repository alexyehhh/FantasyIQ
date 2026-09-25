import { buildLogRows } from "./gameLog";
import { makeEntry, makeScheduleEntry, makeTeam } from "@/test/fixtures";

const game = (id: number, day: number, overrides = {}) =>
  makeScheduleEntry({
    game_id: id,
    game_date: `2026-09-${String(day).padStart(2, "0")}T18:00:00Z`,
    ...overrides,
  });

describe("buildLogRows", () => {
  it("lists games in date order, whatever order they arrive in", () => {
    const rows = buildLogRows([], [game(3, 27), game(1, 6), game(2, 13)], null);

    expect(rows.map((row) => row.gameId)).toEqual([1, 2, 3]);
  });

  it("attaches the player's stat line to a played game and marks the rest upcoming", () => {
    const played = game(1, 6, { status: "final", result: "W", team_score: 24, opponent_score: 17 });
    const stats = makeEntry({ game_id: 1, stats: { points: 12 } });

    const [first, second] = buildLogRows([stats], [played, game(2, 13)], null);

    expect(first.kind).toBe("played");
    expect(first.entry).toBe(stats);
    expect(first.result).toBe("W");
    expect(second.kind).toBe("upcoming");
    expect(second.entry).toBeNull();
  });

  it("keeps a played game with no stat line, e.g. one the player missed", () => {
    const [row] = buildLogRows([], [game(1, 6, { status: "final", result: "L" })], null);

    expect(row.kind).toBe("played");
    expect(row.entry).toBeNull();
  });

  it("treats a game in progress as upcoming", () => {
    const [row] = buildLogRows([], [game(1, 6, { status: "in_progress" })], null);

    expect(row.kind).toBe("upcoming");
    expect(row.status).toBe("in_progress");
  });

  it("lists only this season's games, leaving out stat lines from earlier seasons", () => {
    const lastSeason = makeEntry({ game_id: 50, game_date: "2026-03-01T18:00:00Z" });

    const rows = buildLogRows([lastSeason], [game(1, 6), game(2, 13)], null);

    expect(rows.map((row) => row.gameId)).toEqual([1, 2]);
    expect(rows.every((row) => row.entry === null)).toBe(true);
  });

  it("starts at the season's first game even when the player has only old stats", () => {
    const rows = buildLogRows([makeEntry({ game_id: 50 })], [game(2, 13), game(1, 6)], null);

    expect(rows[0].gameId).toBe(1);
    expect(rows[0].kind).toBe("upcoming");
  });

  it("lists the stat lines themselves, oldest first, when there is no schedule to go by", () => {
    const rows = buildLogRows(
      [
        makeEntry({ game_id: 2, game_date: "2026-01-06T18:00:00Z" }),
        makeEntry({ game_id: 1, game_date: "2026-01-05T18:00:00Z" }),
      ],
      [],
      5,
    );

    expect(rows.map((row) => row.gameId)).toEqual([1, 2]);
    expect(rows.every((row) => row.kind === "played")).toBe(true);
    expect(rows.some((row) => row.kind === "bye")).toBe(false);
  });

  it("lists a live stat line as a game in progress rather than a result when there is no schedule", () => {
    const rows = buildLogRows(
      [makeEntry({ game_id: 1, status: "in_progress" }), makeEntry({ game_id: 2 })],
      [],
      null,
    );

    expect(rows.map((row) => [row.gameId, row.kind, row.status])).toEqual([
      [1, "upcoming", "in_progress"],
      [2, "played", "final"],
    ]);
  });

  it("doesn't duplicate a game that has both a stat line and a schedule entry", () => {
    const rows = buildLogRows(
      [makeEntry({ game_id: 1 })],
      [game(1, 6, { status: "final" })],
      null,
    );

    expect(rows).toHaveLength(1);
  });

  describe("bye week", () => {
    const weeks = [1, 2, 3, 4, 6, 7].map((week, index) => game(index + 1, index + 6, { week }));

    it("places the bye between the weeks either side of it", () => {
      const rows = buildLogRows([], weeks, 5);

      expect(rows.map((row) => (row.kind === "bye" ? "bye" : row.week))).toEqual([
        1, 2, 3, 4, "bye", 6, 7,
      ]);
      expect(rows[4].week).toBe(5);
    });

    it("omits it when the team has no bye", () => {
      expect(buildLogRows([], weeks, null).some((row) => row.kind === "bye")).toBe(false);
    });

    it("puts a bye after the last game when every game is before it", () => {
      const rows = buildLogRows([], weeks, 9);

      expect(rows[rows.length - 1].kind).toBe("bye");
    });

    it("places the bye by this season's weeks, whatever weeks old stat lines were from", () => {
      // Last season's week 17 is not on the schedule, so it is neither listed nor moves the bye.
      const old = makeEntry({ game_id: 99, game_date: "2025-12-28T18:00:00Z", week: 17 });

      const rows = buildLogRows([old], weeks, 5);

      expect(rows.some((row) => row.gameId === 99)).toBe(false);
      expect(rows.findIndex((row) => row.kind === "bye")).toBe(4);
    });

    it("shows no bye when there is no schedule to place it in", () => {
      expect(buildLogRows([], [], 5)).toEqual([]);
    });
  });
});
