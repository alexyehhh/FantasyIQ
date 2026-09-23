import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlayersPage from "./page";
import { listPlayers } from "@/lib/api";

jest.mock("@/lib/api", () => ({
  listPlayers: jest.fn(),
}));

const mockedListPlayers = listPlayers as jest.MockedFunction<typeof listPlayers>;

describe("PlayersPage", () => {
  beforeEach(() => {
    mockedListPlayers.mockReset();
  });

  it("renders the players returned from the API", async () => {
    mockedListPlayers.mockResolvedValue({
      items: [
        {
          id: 1,
          name: "Steph Curry",
          sport: "NBA",
          team_id: 1,
          position: "PG",
          jersey_number: 30,
          active: true,
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });

    render(<PlayersPage />);

    expect(await screen.findByText("Steph Curry")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Steph Curry/ })).toHaveAttribute(
      "href",
      "/players/1",
    );
  });

  it("shows an error message when the backend call fails", async () => {
    mockedListPlayers.mockRejectedValue(new Error("network error"));

    render(<PlayersPage />);

    expect(
      await screen.findByText("Could not load players. Is the backend running?"),
    ).toBeInTheDocument();
  });

  it("re-queries with the typed search term", async () => {
    mockedListPlayers.mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    const user = userEvent.setup();

    render(<PlayersPage />);
    await waitFor(() => expect(mockedListPlayers).toHaveBeenCalledTimes(1));

    await user.type(screen.getByPlaceholderText("Search by name..."), "curry");

    await waitFor(() =>
      expect(mockedListPlayers).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "curry" }),
      ),
    );
  });
});
