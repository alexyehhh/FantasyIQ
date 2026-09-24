import { render, screen, within } from "@testing-library/react";
import DefenseDetailPage from "./page";
import {
  getDefense,
  getDefenseSchedule,
  getDefenseSeason,
  getDefenseStats,
  getScoringPreset,
} from "@/lib/api";
import {
  makeDefenseDetail,
  makeDefenseEntry,
  makeScoringConfig,
  makeSeasonSummary,
  makeUpcoming,
  scheduleFromGames,
} from "@/test/fixtures";

jest.mock("@/lib/api", () => ({
  getDefense: jest.fn(),
  getDefenseStats: jest.fn(),
  getDefenseSchedule: jest.fn(),
  getScoringPreset: jest.fn(),
  getDefenseSeason: jest.fn(),
}));

const notFound = jest.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
jest.mock("next/navigation", () => ({
  notFound: () => notFound(),
}));

const mockedGetDefense = getDefense as jest.MockedFunction<typeof getDefense>;
const mockedGetStats = getDefenseStats as jest.MockedFunction<typeof getDefenseStats>;
const mockedGetSchedule = getDefenseSchedule as jest.MockedFunction<typeof getDefenseSchedule>;
const mockedGetScoring = getScoringPreset as jest.MockedFunction<typeof getScoringPreset>;
const mockedGetSeason = getDefenseSeason as jest.MockedFunction<typeof getDefenseSeason>;

async function renderPage(id = "7") {
  render(await DefenseDetailPage({ params: Promise.resolve({ id }) }));
}

describe("DefenseDetailPage", () => {
  beforeEach(() => {
    mockedGetDefense.mockReset();
    mockedGetStats.mockReset();
    mockedGetSchedule.mockReset();
    mockedGetScoring.mockReset();
    mockedGetSeason.mockReset();
    mockedGetSeason.mockResolvedValue(null);
    mockedGetDefense.mockResolvedValue(makeDefenseDetail());
    mockedGetStats.mockResolvedValue([makeDefenseEntry()]);
    mockedGetSchedule.mockResolvedValue([]);
    mockedGetScoring.mockResolvedValue(null);
    notFound.mockClear();
  });

  it("renders the defense's header, trend chart, averages and game log", async () => {
    await renderPage();

    expect(screen.getByRole("heading", { name: "Cincinnati Bengals" })).toBeInTheDocument();
    expect(screen.getByLabelText("Game trend")).toBeInTheDocument();
    expect(screen.getByLabelText("Averages")).toBeInTheDocument();
    expect(screen.getByLabelText("Game log")).toBeInTheDocument();
  });

  it("asks for a whole season of games, the schedule, and the NFL scoring", async () => {
    await renderPage();

    expect(mockedGetDefense).toHaveBeenCalledWith(7);
    expect(mockedGetStats).toHaveBeenCalledWith(7, 200, "current");
    expect(mockedGetSchedule).toHaveBeenCalledWith(7);
    expect(mockedGetScoring).toHaveBeenCalledWith("NFL");
  });

  it("lists sacks, points allowed and the rest as game log columns, with the defense's fantasy points", async () => {
    await renderPage();

    const log = screen.getByLabelText("Game log");
    for (const name of ["SCK", "INT", "FR", "DTD", "RTD", "SAF", "BLK", "4DS", "PA", "YA", "FPTS"]) {
      expect(within(log).getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(within(log).getByRole("cell", { name: "12" })).toHaveClass("font-bold");
  });

  it("describes the defense's scoring under the game log", async () => {
    mockedGetScoring.mockResolvedValue(makeScoringConfig());

    await renderPage();

    expect(
      screen.getByText("FPTS uses Test league scoring: Sacks +1, Points allowed 0 +10, 1+ 0."),
    ).toBeInTheDocument();
  });

  it("lists the upcoming games and the bye week in the game log", async () => {
    const played = [makeDefenseEntry()];
    mockedGetSchedule.mockResolvedValue([...scheduleFromGames(played), ...makeUpcoming(2)]);

    await renderPage();

    expect(screen.getByLabelText("Game log")).toHaveTextContent("1 played · 2 upcoming");
    expect(screen.getByLabelText("Game log")).toHaveTextContent("Week 6 · Bye");
  });

  it("shows an empty state, but still the schedule, before any game has been ingested", async () => {
    mockedGetStats.mockResolvedValue([]);
    mockedGetSchedule.mockResolvedValue(makeUpcoming(3));

    await renderPage();

    expect(screen.getByText("No game stats yet")).toBeInTheDocument();
    expect(screen.getByLabelText("Game log")).toHaveTextContent("0 played · 3 upcoming");
  });

  it("copes with a stats request that returns nothing", async () => {
    mockedGetStats.mockResolvedValue(null);
    mockedGetSchedule.mockResolvedValue(null);

    await renderPage();

    expect(screen.getByText("No game stats yet")).toBeInTheDocument();
  });

  it("is a 404 for an unknown team and for an id that isn't a number", async () => {
    mockedGetDefense.mockResolvedValue(null);
    await expect(renderPage()).rejects.toThrow("NEXT_NOT_FOUND");

    notFound.mockClear();
    await expect(renderPage("abc")).rejects.toThrow("NEXT_NOT_FOUND");
    expect(mockedGetDefense).toHaveBeenCalledTimes(1); // the bad id never reached the API
  });

  it("shows the defense's season totals ranked among the defenses", async () => {
    mockedGetSeason.mockResolvedValue(
      makeSeasonSummary({
        position_group: "DEF",
        stats: {
          fantasy_points: { total: 34, rank: 1, tied: false },
          sacks: { total: 8, rank: 2, tied: true },
          interceptions: { total: 0, rank: 24, tied: true },
          points_allowed: { total: 26, rank: 5, tied: false },
          yards_allowed: { total: 656, rank: 11, tied: false },
        },
      }),
    );

    await renderPage();

    expect(mockedGetSeason).toHaveBeenCalledWith(7);
    const sacks = screen.getByRole("group", { name: "Sacks" });
    expect(sacks).toHaveTextContent("8");
    expect(sacks).toHaveTextContent("T-#2");
    expect(sacks).toHaveTextContent("of 32 DEF");
    expect(screen.getByRole("group", { name: "Points allowed" })).toHaveTextContent("#5");
  });

  it("links back to the players list", async () => {
    await renderPage();

    expect(screen.getByRole("link", { name: /Back to players/ })).toHaveAttribute("href", "/players");
  });
});
