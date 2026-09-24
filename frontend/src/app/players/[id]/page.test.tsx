import { render, screen } from "@testing-library/react";
import PlayerDetailPage from "./page";
import { getPlayer, getPlayerSchedule, getPlayerStats } from "@/lib/api";
import {
  makeEntry,
  makePlayerDetail,
  makeScheduleEntry,
  makeTeam,
  makeUpcoming,
  scheduleFromGames,
} from "@/test/fixtures";

jest.mock("@/lib/api", () => ({
  getPlayer: jest.fn(),
  getPlayerStats: jest.fn(),
  getPlayerSchedule: jest.fn(),
}));

const notFound = jest.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});
jest.mock("next/navigation", () => ({
  notFound: () => notFound(),
}));

const mockedGetPlayer = getPlayer as jest.MockedFunction<typeof getPlayer>;
const mockedGetPlayerStats = getPlayerStats as jest.MockedFunction<
  typeof getPlayerStats
>;
const mockedGetPlayerSchedule = getPlayerSchedule as jest.MockedFunction<
  typeof getPlayerSchedule
>;

async function renderPage(id = "1") {
  render(await PlayerDetailPage({ params: Promise.resolve({ id }) }));
}

describe("PlayerDetailPage", () => {
  beforeEach(() => {
    mockedGetPlayer.mockReset();
    mockedGetPlayerStats.mockReset();
    mockedGetPlayerSchedule.mockReset();
    mockedGetPlayerSchedule.mockResolvedValue([]);
    notFound.mockClear();
  });

  it("renders the player's header and stats", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail());
    mockedGetPlayerStats.mockResolvedValue([makeEntry()]);

    await renderPage();

    expect(screen.getByRole("heading", { name: "Steph Curry" })).toBeInTheDocument();
    expect(screen.getByText("Golden State Warriors · NBA")).toBeInTheDocument();
    expect(screen.getByLabelText("Game trend")).toBeInTheDocument();
    expect(screen.getByLabelText("Game log")).toBeInTheDocument();
  });

  it("asks for a whole season of games so the log can list every one", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail());
    mockedGetPlayerStats.mockResolvedValue([]);

    await renderPage();

    expect(mockedGetPlayerStats).toHaveBeenCalledWith(1, 200);
  });

  it("lists the team's upcoming games in the game log", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail());
    mockedGetPlayerStats.mockResolvedValue([makeEntry()]);
    mockedGetPlayerSchedule.mockResolvedValue([...scheduleFromGames([makeEntry()]), ...makeUpcoming(3)]);

    await renderPage();

    expect(screen.getByLabelText("Game log")).toHaveTextContent("1 played · 3 upcoming");
    expect(mockedGetPlayerSchedule).toHaveBeenCalledWith(1);
  });

  it("shows the team's bye week in the header and the game log", async () => {
    mockedGetPlayer.mockResolvedValue(
      makePlayerDetail({ sport: "NFL", position: "QB", team: makeTeam({ bye_week: 5 }) }),
    );
    mockedGetPlayerStats.mockResolvedValue([makeEntry({ stats: { passing_yards: 200 } })]);
    mockedGetPlayerSchedule.mockResolvedValue(
      [4, 6].map((week, index) =>
        makeScheduleEntry({ game_id: index + 1, week, game_date: `2999-10-0${index + 4}T18:00:00Z` }),
      ),
    );

    await renderPage();

    expect(screen.getByText("Bye week 5")).toBeInTheDocument();
    expect(screen.getByText("Week 5 · Bye")).toBeInTheDocument();
  });

  it("links back to the players list", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail());
    mockedGetPlayerStats.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByRole("link", { name: /Back to players/ })).toHaveAttribute(
      "href",
      "/players",
    );
  });

  it("shows the injury note only when the player has an injury report", async () => {
    mockedGetPlayer.mockResolvedValue(
      makePlayerDetail({
        injury_status: "Out",
        injury: {
          status: "Out",
          type: "Knee",
          note: "Sprained knee; re-evaluated in two weeks.",
          updated_at: "2026-03-10T15:00:00Z",
        },
      }),
    );
    mockedGetPlayerStats.mockResolvedValue([]);

    await renderPage();

    const note = screen.getByLabelText("Player note");
    expect(note).toHaveTextContent("Out");
    expect(note).toHaveTextContent("Knee");
    expect(note).toHaveTextContent("Sprained knee; re-evaluated in two weeks.");
    expect(note).toHaveTextContent("Updated Mar 10");
  });

  it("has no injury note for a healthy player", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail());
    mockedGetPlayerStats.mockResolvedValue([]);

    await renderPage();

    expect(screen.queryByLabelText("Player note")).not.toBeInTheDocument();
  });

  it("shows an empty state when the player has no stats yet", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail());
    mockedGetPlayerStats.mockResolvedValue(null);

    await renderPage();

    expect(screen.getByText("No game stats yet")).toBeInTheDocument();
  });

  it("says kickers aren't tracked yet instead of showing zeros", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail({ sport: "NFL", position: "PK" }));
    mockedGetPlayerStats.mockResolvedValue([makeEntry({ stats: { passing_yards: 0 } })]);
    mockedGetPlayerSchedule.mockResolvedValue(makeUpcoming(2));

    await renderPage();

    expect(screen.getByText("Stats aren't tracked for this position yet")).toBeInTheDocument();
    expect(screen.getByLabelText("Game log")).toHaveTextContent("upcoming");
  });

  it("shows the opponent and result in the game log", async () => {
    mockedGetPlayer.mockResolvedValue(makePlayerDetail());
    mockedGetPlayerStats.mockResolvedValue([
      makeEntry({
        opponent: makeTeam({ abbreviation: "LAL" }),
        is_home: true,
        team_score: 110,
        opponent_score: 104,
        result: "W",
      }),
    ]);

    await renderPage();

    expect(screen.getByText("vs LAL")).toBeInTheDocument();
    expect(screen.getByText("110–104")).toBeInTheDocument();
  });

  it("calls notFound when the player doesn't exist", async () => {
    mockedGetPlayer.mockResolvedValue(null);

    await expect(
      PlayerDetailPage({ params: Promise.resolve({ id: "999" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });

  it("calls notFound when the id param isn't numeric", async () => {
    await expect(
      PlayerDetailPage({ params: Promise.resolve({ id: "abc" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(mockedGetPlayer).not.toHaveBeenCalled();
  });
});
