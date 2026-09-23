import { render, screen } from "@testing-library/react";
import PlayerDetailPage from "./page";
import { getPlayer, getPlayerStats } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  getPlayer: jest.fn(),
  getPlayerStats: jest.fn(),
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

describe("PlayerDetailPage", () => {
  beforeEach(() => {
    mockedGetPlayer.mockReset();
    mockedGetPlayerStats.mockReset();
    notFound.mockClear();
  });

  it("renders the player's info and stat chart", async () => {
    mockedGetPlayer.mockResolvedValue({
      id: 1,
      name: "Steph Curry",
      sport: "NBA",
      team_id: 1,
      position: "PG",
      jersey_number: 30,
      active: true,
      external_id: "espn-1",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockedGetPlayerStats.mockResolvedValue([
      { game_id: 1, game_date: "2026-01-05T00:00:00Z", stats: { points: 30 } },
    ]);

    const jsx = await PlayerDetailPage({ params: Promise.resolve({ id: "1" }) });
    render(jsx);

    expect(screen.getByRole("heading", { name: "Steph Curry" })).toBeInTheDocument();
    expect(screen.getByText(/NBA · PG · #30/)).toBeInTheDocument();
    expect(mockedGetPlayerStats).toHaveBeenCalledWith(1, 20);
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
