import { act, fireEvent, render, screen } from "@testing-library/react";
import ScoresStrip, { ROTATE_MS } from "./ScoresStrip";
import { getScoreboard } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/usePolling";
import { makeTeam } from "@/test/fixtures";
import type { ScoreboardGame } from "@/lib/api";

jest.mock("@/lib/api", () => ({ getScoreboard: jest.fn() }));

const scoreboard = jest.mocked(getScoreboard);

function makeGame(overrides: Partial<ScoreboardGame> = {}): ScoreboardGame {
  return {
    game_id: 1,
    start_time: "2026-09-27T17:00:00Z",
    status: "final",
    week: 3,
    home_team: makeTeam({ id: 1, name: "Lions", abbreviation: "DET" }),
    away_team: makeTeam({ id: 2, name: "Jets", abbreviation: "NYJ" }),
    home_score: 31,
    away_score: 24,
    ...overrides,
  };
}

const second = makeGame({
  game_id: 2,
  home_team: makeTeam({ id: 3, name: "49ers", abbreviation: "SF" }),
  away_team: makeTeam({ id: 4, name: "Cardinals", abbreviation: "ARI" }),
  home_score: 36,
  away_score: 30,
});

const tick = (ms = 0) => act(async () => jest.advanceTimersByTime(ms));

beforeEach(() => {
  jest.useFakeTimers();
  scoreboard.mockReset();
});

afterEach(() => jest.useRealTimers());

describe("ScoresStrip", () => {
  it("shows the first game with its score and status", async () => {
    scoreboard.mockResolvedValue({ week: 3, games: [makeGame(), second] });
    render(<ScoresStrip />);
    await tick();

    expect(screen.getByText("Scores · Week 3")).toBeInTheDocument();
    expect(screen.getByText("Game 1 of 2")).toBeInTheDocument();
    expect(screen.getAllByText("DET").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NYJ").length).toBeGreaterThan(0);
    expect(screen.getByText("31")).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(screen.getByText("Final")).toBeInTheDocument();
    expect(scoreboard).toHaveBeenCalledWith("NFL");
  });

  it("rotates to the next game automatically every 5 seconds, and loops back", async () => {
    scoreboard.mockResolvedValue({ week: 3, games: [makeGame(), second] });
    render(<ScoresStrip />);
    await tick();

    await tick(ROTATE_MS);
    expect(screen.getAllByText("SF").length).toBeGreaterThan(0);
    expect(screen.queryByText("DET")).not.toBeInTheDocument();

    await tick(ROTATE_MS);
    expect(screen.getAllByText("DET").length).toBeGreaterThan(0);
  });

  it("jumps straight to a game when its dot is clicked", async () => {
    scoreboard.mockResolvedValue({ week: 3, games: [makeGame(), second] });
    render(<ScoresStrip />);
    await tick();

    fireEvent.click(screen.getByRole("tab", { name: "ARI at SF" }));

    expect(screen.getAllByText("SF").length).toBeGreaterThan(0);
  });

  it("marks an in-progress game as live", async () => {
    scoreboard.mockResolvedValue({
      week: 3,
      games: [makeGame({ status: "in_progress", home_score: 10, away_score: 7 })],
    });
    render(<ScoresStrip />);
    await tick();

    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("says so when nothing is scheduled yet", async () => {
    scoreboard.mockResolvedValue({ week: null, games: [] });
    render(<ScoresStrip />);
    await tick();

    expect(screen.getByText("No games scheduled yet.")).toBeInTheDocument();
  });

  it("silently refetches every 30 seconds so a live score updates on its own", async () => {
    scoreboard.mockResolvedValue({
      week: 3,
      games: [makeGame({ status: "in_progress", home_score: 10, away_score: 7 })],
    });
    render(<ScoresStrip />);
    await tick();
    expect(screen.getByText("7")).toBeInTheDocument();

    scoreboard.mockResolvedValue({
      week: 3,
      games: [makeGame({ status: "in_progress", home_score: 17, away_score: 14 })],
    });
    await tick(POLL_INTERVAL_MS);

    expect(screen.getByText("14")).toBeInTheDocument();
    expect(scoreboard).toHaveBeenCalledTimes(2);
  });
});
