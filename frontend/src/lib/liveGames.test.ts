import { GRACE_MS, LEAD_MS, hasLiveGame } from "./liveGames";

const NOW = Date.parse("2026-09-27T18:00:00Z");
const game = (status: string, offsetMs: number) => ({
  status: status as "scheduled" | "in_progress" | "final",
  game_date: new Date(NOW + offsetMs).toISOString(),
});

describe("hasLiveGame", () => {
  it("is true while a game is in progress, however long ago it started", () => {
    expect(hasLiveGame([game("in_progress", -5 * 3_600_000)], NOW)).toBe(true);
  });

  it("is false with only finished games and games well in the future", () => {
    expect(hasLiveGame([game("final", -3_600_000), game("scheduled", 3 * 86_400_000)], NOW)).toBe(
      false,
    );
    expect(hasLiveGame([], NOW)).toBe(false);
  });

  it("starts watching a little before kickoff so it notices the game begin", () => {
    expect(hasLiveGame([game("scheduled", LEAD_MS)], NOW)).toBe(true);
    expect(hasLiveGame([game("scheduled", LEAD_MS + 1000)], NOW)).toBe(false);
  });

  it("keeps watching briefly for a game still called scheduled after its start time", () => {
    expect(hasLiveGame([game("scheduled", -GRACE_MS)], NOW)).toBe(true);
    // Long past its start and still not started (postponed): not worth polling for.
    expect(hasLiveGame([game("scheduled", -GRACE_MS - 1000)], NOW)).toBe(false);
  });
});
