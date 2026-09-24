import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlayersPage from "./page";
import { listPlayers } from "@/lib/api";
import { makePlayerListItem as makePlayerSummary, makeTeam } from "@/test/fixtures";

jest.mock("@/lib/api", () => ({
  listPlayers: jest.fn(),
}));

const mockedListPlayers = listPlayers as jest.MockedFunction<typeof listPlayers>;

function respondWith(items: ReturnType<typeof makePlayerSummary>[], total = items.length) {
  mockedListPlayers.mockResolvedValue({ items, total, limit: 50, offset: 0 });
}

describe("PlayersPage", () => {
  beforeEach(() => {
    mockedListPlayers.mockReset();
  });

  it("renders the players returned from the API", async () => {
    respondWith([makePlayerSummary()]);

    render(<PlayersPage />);

    expect(await screen.findByText("Steph Curry")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Steph Curry/ })).toHaveAttribute(
      "href",
      "/players/1",
    );
  });

  it("shows each player's team, position, number and status", async () => {
    respondWith([
      makePlayerSummary({ position: "G", jersey_number: 30, injury_status: "Questionable" }),
    ]);

    render(<PlayersPage />);

    const row = await screen.findByRole("link", { name: /Steph Curry/ });
    expect(row).toHaveTextContent("Golden State Warriors");
    expect(row).toHaveTextContent("G");
    expect(row).toHaveTextContent("#30");
    expect(row).toHaveTextContent("42.5");
    expect(row).toHaveTextContent("Questionable");
  });

  it("copes with players missing a team, number or position", async () => {
    respondWith([
      makePlayerSummary({ team: null, team_id: null, position: null, jersey_number: null }),
    ]);

    render(<PlayersPage />);

    const row = await screen.findByRole("link", { name: /Steph Curry/ });
    expect(row).toHaveTextContent("—");
    expect(row).not.toHaveTextContent("#");
  });

  it("shows the team logo when the team has one", async () => {
    respondWith([makePlayerSummary({ team: makeTeam({ logo_url: "https://img.example/gsw.png" }) })]);

    const { container } = render(<PlayersPage />);
    await screen.findByText("Steph Curry");

    expect(container.querySelector('img[src="https://img.example/gsw.png"]')).toBeInTheDocument();
  });

  it("shows an error message when the backend call fails", async () => {
    mockedListPlayers.mockRejectedValue(new Error("network error"));

    render(<PlayersPage />);

    expect(
      await screen.findByText("Could not load players. Is the backend running?"),
    ).toBeInTheDocument();
  });

  it("says so when nothing matches", async () => {
    respondWith([]);

    render(<PlayersPage />);

    expect(await screen.findByText("No players found")).toBeInTheDocument();
  });

  it("re-queries with the typed search term", async () => {
    respondWith([]);
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

  it("puts NFL before NBA, both in the description and on the buttons", () => {
    respondWith([]);

    render(<PlayersPage />);

    expect(screen.getByText(/Search NFL and NBA players/)).toBeInTheDocument();
    const sports = within(screen.getByRole("group", { name: "Sport" })).getAllByRole("button");
    expect(sports.map((button) => button.textContent)).toEqual(["NFL", "NBA"]);
  });

  it("has no All sports option and starts on NFL quarterbacks", async () => {
    respondWith([]);

    render(<PlayersPage />);

    expect(screen.queryByRole("button", { name: /All sports/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "NFL" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "QB" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() =>
      expect(mockedListPlayers).toHaveBeenLastCalledWith(
        expect.objectContaining({ sport: "NFL", positions: ["QB"] }),
      ),
    );
  });

  it("offers the fantasy position buttons in order, with DEF shown but disabled", () => {
    respondWith([]);

    render(<PlayersPage />);

    const positions = within(screen.getByRole("group", { name: "Position" })).getAllByRole("button");
    expect(positions.map((button) => button.textContent)).toEqual([
      "QB", "RB", "WR", "TE", "W/R/T", "K", "DEF",
    ]);
    expect(screen.getByRole("button", { name: "DEF" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "DEF" })).toHaveAttribute(
      "title",
      "Team defenses aren't tracked yet",
    );
  });

  it.each([
    ["RB", ["RB", "FB"]],
    ["WR", ["WR"]],
    ["TE", ["TE"]],
    ["W/R/T", ["RB", "FB", "WR", "TE"]],
    ["K", ["PK"]],
  ])("filters to the %s position codes when that button is pressed", async (label, codes) => {
    respondWith([]);
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(mockedListPlayers).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: label }));

    await waitFor(() =>
      expect(mockedListPlayers).toHaveBeenLastCalledWith(
        expect.objectContaining({ sport: "NFL", positions: codes }),
      ),
    );
    expect(screen.getByRole("button", { name: label })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "QB" })).toHaveAttribute("aria-pressed", "false");
  });

  it("does nothing when the disabled DEF button is pressed", async () => {
    respondWith([]);
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(mockedListPlayers).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole("button", { name: "DEF" }));

    expect(screen.getByRole("button", { name: "QB" })).toHaveAttribute("aria-pressed", "true");
    expect(mockedListPlayers).toHaveBeenCalledTimes(1);
  });

  it("keeps the search term when the position changes", async () => {
    respondWith([]);
    const user = userEvent.setup();
    render(<PlayersPage />);
    await user.type(screen.getByPlaceholderText("Search by name..."), "smith");

    await user.click(screen.getByRole("button", { name: "WR" }));

    await waitFor(() =>
      expect(mockedListPlayers).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "smith", positions: ["WR"] }),
      ),
    );
  });

  describe("NBA", () => {
    async function openNba() {
      respondWith([]);
      const user = userEvent.setup();
      render(<PlayersPage />);
      await waitFor(() => expect(mockedListPlayers).toHaveBeenCalledTimes(1));
      await user.click(screen.getByRole("button", { name: "NBA" }));
      return user;
    }

    it("has its own position buttons: G, F, C and Util", async () => {
      await openNba();

      const positions = within(screen.getByRole("group", { name: "Position" })).getAllByRole("button");
      expect(positions.map((button) => button.textContent)).toEqual(["G", "F", "C", "Util"]);
      expect(positions.every((button) => !(button as HTMLButtonElement).disabled)).toBe(true);
    });

    it("starts on the first NBA position rather than carrying over QB", async () => {
      await openNba();

      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(
          expect.objectContaining({ sport: "NBA", positions: ["G", "PG", "SG"] }),
        ),
      );
      expect(screen.getByRole("button", { name: "G" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.queryByRole("button", { name: "QB" })).not.toBeInTheDocument();
    });

    it.each([
      ["F", ["F", "SF", "PF"]],
      ["C", ["C"]],
      ["Util", []],
    ])("filters to %s", async (label, codes) => {
      const user = await openNba();

      await user.click(screen.getByRole("button", { name: label }));

      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(
          expect.objectContaining({ sport: "NBA", positions: codes }),
        ),
      );
    });

    it("goes back to QB when switching back to NFL", async () => {
      const user = await openNba();

      await user.click(screen.getByRole("button", { name: "NFL" }));

      expect(screen.getByRole("button", { name: "QB" })).toHaveAttribute("aria-pressed", "true");
      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(
          expect.objectContaining({ sport: "NFL", positions: ["QB"] }),
        ),
      );
    });
  });

  describe("ranking and paging", () => {
    it("asks for players ranked by fantasy points, 50 at a time from the top", async () => {
      respondWith([]);

      render(<PlayersPage />);

      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(
          expect.objectContaining({ sort: "fantasy_points", limit: 50, offset: 0 }),
        ),
      );
    });

    it("shows each player's fantasy points, and a dash when there are none", async () => {
      respondWith([
        makePlayerSummary({ id: 1, name: "Scorer", fantasy_points: 76.5 }),
        makePlayerSummary({ id: 2, name: "Unscored", fantasy_points: null }),
        makePlayerSummary({ id: 3, name: "Rounded", fantasy_points: 20 }),
      ]);

      render(<PlayersPage />);

      expect(await screen.findByRole("link", { name: /Scorer/ })).toHaveTextContent("76.5");
      expect(screen.getByRole("link", { name: /Unscored/ })).not.toHaveTextContent(/\d\.\d/);
      expect(screen.getByRole("link", { name: /Rounded/ })).toHaveTextContent("20");
      expect(screen.getByText("FPTS")).toBeInTheDocument();
    });

    it("shows a dash for kickers, whose fantasy points aren't tracked", async () => {
      respondWith([
        makePlayerSummary({ sport: "NFL", position: "PK", fantasy_points: 0, jersey_number: null }),
      ]);

      render(<PlayersPage />);

      const row = await screen.findByRole("link", { name: /Steph Curry/ });
      expect(row).not.toHaveTextContent("0"); // no "0" or "0.0" points
      expect(row).toHaveTextContent("—");
    });

    it("says where in the ranking the page is", async () => {
      respondWith([makePlayerSummary()], 214);

      render(<PlayersPage />);

      expect(
        await screen.findByText(/Showing 1–1 of 214 players, most fantasy points first/),
      ).toBeInTheDocument();
    });

    function pageOfPlayers(count: number, total: number) {
      respondWith(
        Array.from({ length: count }, (_, index) =>
          makePlayerSummary({ id: index + 1, name: `Player ${index + 1}` }),
        ),
        total,
      );
    }

    it("offers Previous 50 and Next 50, with Previous off on the first page", async () => {
      pageOfPlayers(50, 120);

      render(<PlayersPage />);

      await screen.findByText("Player 1");
      expect(screen.getByRole("button", { name: "Next 50" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Previous 50" })).toBeDisabled();
    });

    it("moves to the next 50 and back", async () => {
      pageOfPlayers(50, 120);
      const user = userEvent.setup();
      render(<PlayersPage />);
      await screen.findByText("Player 1");

      await user.click(screen.getByRole("button", { name: "Next 50" }));
      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 })),
      );

      await user.click(screen.getByRole("button", { name: "Previous 50" }));
      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 })),
      );
    });

    it("turns Next off on the last page", async () => {
      pageOfPlayers(50, 100);
      const user = userEvent.setup();
      render(<PlayersPage />);
      await screen.findByText("Player 1");

      await user.click(screen.getByRole("button", { name: "Next 50" }));

      await waitFor(() => expect(screen.getByRole("button", { name: "Next 50" })).toBeDisabled());
      expect(screen.getByRole("button", { name: "Previous 50" })).toBeEnabled();
    });

    it("has no paging when everything fits on one page", async () => {
      pageOfPlayers(10, 10);

      render(<PlayersPage />);

      await screen.findByText("Player 1");
      expect(screen.getByRole("button", { name: "Next 50" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Previous 50" })).toBeDisabled();
    });

    it("scrolls back to the top of the page when Next 50 or Previous 50 is pressed", async () => {
      pageOfPlayers(50, 120);
      const user = userEvent.setup();
      render(<PlayersPage />);
      await screen.findByText("Player 1");
      (window.scrollTo as jest.Mock).mockClear();

      await user.click(screen.getByRole("button", { name: "Next 50" }));
      expect(window.scrollTo).toHaveBeenCalledTimes(1);
      expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 0 });

      await user.click(await screen.findByRole("button", { name: "Previous 50" }));
      expect(window.scrollTo).toHaveBeenCalledTimes(2);
      expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 0 });
    });

    it("doesn't scroll when the list is filtered rather than paged", async () => {
      pageOfPlayers(50, 120);
      const user = userEvent.setup();
      render(<PlayersPage />);
      await screen.findByText("Player 1");
      (window.scrollTo as jest.Mock).mockClear();

      await user.click(screen.getByRole("button", { name: "WR" }));

      expect(window.scrollTo).not.toHaveBeenCalled();
    });

    it.each([
      ["a new position", async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("button", { name: "WR" }))],
      ["a new sport", async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole("button", { name: "NBA" }))],
      ["a search", async (user: ReturnType<typeof userEvent.setup>) => user.type(screen.getByPlaceholderText("Search by name..."), "x")],
    ])("returns to the top of the ranking after %s", async (_name, change) => {
      pageOfPlayers(50, 200);
      const user = userEvent.setup();
      render(<PlayersPage />);
      await screen.findByText("Player 1");
      await user.click(screen.getByRole("button", { name: "Next 50" }));
      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 50 })),
      );

      await change(user);

      await waitFor(() =>
        expect(mockedListPlayers).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 0 })),
      );
    });
  });

  it("shows a kicker's position as K", async () => {
    respondWith([makePlayerSummary({ sport: "NFL", position: "PK" })]);

    render(<PlayersPage />);

    const row = await screen.findByRole("link", { name: /Steph Curry/ });
    expect(row).toHaveTextContent("K");
    expect(row).not.toHaveTextContent("PK");
  });

});
