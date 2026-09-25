import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StartPage from "./page";
import {
  getProjectionSources,
  getProjections,
  getScoringPreset,
  getTopProjections,
  listDefenses,
  listPlayers,
} from "@/lib/api";
import {
  makeDefenseListItem,
  makePlayerListItem,
  makeProjectionEntry as entry,
  makeScoringConfig,
} from "@/test/fixtures";

jest.mock("@/lib/api", () => ({
  getProjectionSources: jest.fn(),
  getProjections: jest.fn(),
  getScoringPreset: jest.fn(),
  getTopProjections: jest.fn(),
  listDefenses: jest.fn(),
  listPlayers: jest.fn(),
}));

const sources = jest.mocked(getProjectionSources);
const projections = jest.mocked(getProjections);
const preset = jest.mocked(getScoringPreset);
const top = jest.mocked(getTopProjections);
const players = jest.mocked(listPlayers);
const defenses = jest.mocked(listDefenses);

const gibbs = entry({ id: 1, name: "Jahmyr Gibbs", fantasy_points: 23.5 });
const lamb = entry({ id: 2, name: "CeeDee Lamb", position: "WR", fantasy_points: 18.1, std: 8 });
const chase = entry({ id: 3, name: "Ja'Marr Chase", position: "WR", fantasy_points: 16.7, std: 8 });

function respond(items = [gibbs, lamb, chase]) {
  top.mockResolvedValue({ source: "sleeper", scoring: "FantasyIQ", week: 3, items, total: items.length });
  projections.mockImplementation(async (query) => {
    const ids = query.playerIds ?? [];
    const found = [gibbs, lamb, chase].filter((e) => ids.includes(e.id));
    return {
      source: query.source,
      scoring: query.scoring?.name ?? "FantasyIQ standard (PPR)",
      week: 3,
      items: found.map((e) => ({ ...e, source: query.source, chance_best: 0.5 })),
      total: null,
    };
  });
}

beforeEach(() => {
  window.localStorage.clear();
  window.history.replaceState(null, "", "/start");
  jest.resetAllMocks();
  sources.mockResolvedValue([
    { name: "sleeper", label: "Sleeper", description: "Rotowire's projections", sports: ["NBA", "NFL"] },
  ]);
  preset.mockResolvedValue(makeScoringConfig({ sport: "NFL", player_weights: { receptions: 1 } }));
  respond();
});

async function open() {
  const user = userEvent.setup();
  render(<StartPage />);
  await screen.findByRole("button", { name: "Add Jahmyr Gibbs to the comparison" });
  return user;
}

describe("StartPage", () => {
  it("lists the top players for the slot with the week and asks for the FLEX slot first", async () => {
    await open();

    expect(top).toHaveBeenCalledWith(
      expect.objectContaining({ sport: "NFL", slot: "FLEX", source: "sleeper", week: null }),
    );
    expect(screen.getByText("Week 3")).toBeInTheDocument();
    expect(screen.getByText("23.5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "FLEX" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows Sleeper as the one source, as a label rather than a menu with a single choice", async () => {
    await open();

    expect(screen.getByText("Source")).toBeInTheDocument();
    expect(screen.getByText("Sleeper", { selector: "div" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Source" })).not.toBeInTheDocument();
  });

  it("writes each row's position, team and opponent as 'RB · DET vs NYJ' or 'WR · DAL @ BAL'", async () => {
    top.mockResolvedValue({
      source: "sleeper",
      scoring: "x",
      week: 3,
      total: 2,
      items: [
        gibbs,
        entry({
          id: 9,
          name: "Zay Flowers",
          position: "WR",
          team: { ...gibbs.team!, abbreviation: "BAL" },
          game: { ...gibbs.game!, is_home: false, opponent: { ...gibbs.game!.opponent, abbreviation: "DAL" } },
        }),
      ],
    });
    render(<StartPage />);

    expect(await screen.findByText("RB · DET vs NYJ")).toBeInTheDocument();
    expect(screen.getByText("WR · BAL @ DAL")).toBeInTheDocument();
  });

  it("needs two players before it will give advice", async () => {
    const user = await open();
    const advise = screen.getByRole("button", { name: "View advice" });
    expect(advise).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Add Jahmyr Gibbs to the comparison" }));
    expect(advise).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Add CeeDee Lamb to the comparison" }));

    expect(advise).toBeEnabled();
  });

  it("compares the chosen players and gives a verdict", async () => {
    const user = await open();
    await user.click(screen.getByRole("button", { name: "Add Jahmyr Gibbs to the comparison" }));
    await user.click(screen.getByRole("button", { name: "Add CeeDee Lamb to the comparison" }));

    await user.click(screen.getByRole("button", { name: "View advice" }));

    expect(await screen.findByRole("heading", { name: "Start Jahmyr Gibbs" })).toBeInTheDocument();
    await waitFor(() => expect(projections).toHaveBeenCalledTimes(1));
    expect(projections.mock.calls[0][0]).toEqual(
      expect.objectContaining({ source: "sleeper", week: 3, playerIds: [1, 2], defenseIds: [] }),
    );
    expect(screen.queryByText(/Recent form|Blend/)).not.toBeInTheDocument();
    const advice = screen.getByRole("region", { name: "Start/sit advice" });
    expect(within(advice).getAllByText("Start")).toHaveLength(1);
    expect(within(advice).getAllByText("Sit")).toHaveLength(1);
  });

  it("recomputes the advice under a different scoring, sending the changed weights", async () => {
    const user = await open();
    await user.click(screen.getByRole("button", { name: "Add Jahmyr Gibbs to the comparison" }));
    await user.click(screen.getByRole("button", { name: "Add CeeDee Lamb to the comparison" }));
    await user.click(screen.getByRole("button", { name: "View advice" }));
    await screen.findByRole("heading", { name: "Start Jahmyr Gibbs" });

    await user.selectOptions(screen.getByLabelText("Scoring"), "Half-PPR");

    await waitFor(() => {
      const last = projections.mock.calls[projections.mock.calls.length - 1][0];
      expect(last.scoring?.name).toBe("Half-PPR");
      expect(last.scoring?.player_weights.receptions).toBe(0.5);
    });
    expect(top).toHaveBeenLastCalledWith(
      expect.objectContaining({ scoring: expect.objectContaining({ name: "Half-PPR" }) }),
    );
  });

  it("switches the slot and asks the backend again", async () => {
    const user = await open();

    await user.click(screen.getByRole("button", { name: "WR" }));

    await waitFor(() => expect(top).toHaveBeenLastCalledWith(expect.objectContaining({ slot: "WR" })));
  });

  it("steps through the weeks", async () => {
    const user = await open();

    await user.click(screen.getByRole("button", { name: "Next week" }));

    await waitFor(() => expect(top).toHaveBeenLastCalledWith(expect.objectContaining({ week: 4 })));
    await user.click(screen.getByRole("button", { name: "Current week" }));
    await waitFor(() => expect(top).toHaveBeenLastCalledWith(expect.objectContaining({ week: null })));
  });

  it("adds a player from the search, including team defenses", async () => {
    players.mockResolvedValue({ items: [makePlayerListItem({ id: 7, name: "Justin Jefferson", position: "WR", sport: "NFL" })], total: 1, limit: 8, offset: 0 });
    defenses.mockResolvedValue({ items: [makeDefenseListItem({ id: 33, name: "Justice Squad" })], total: 1, limit: 3, offset: 0 });
    const user = await open();

    await user.type(screen.getByRole("combobox", { name: "Add a player" }), "just");
    await user.click(await screen.findByRole("option", { name: /Justin Jefferson/ }));
    await user.type(screen.getByRole("combobox", { name: "Add a player" }), "just");
    await user.click(await screen.findByRole("option", { name: /Justice Squad D\/ST/ }));

    expect(screen.getByRole("button", { name: "Remove Justin Jefferson" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove Justice Squad D/ST" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View advice" }));
    await waitFor(() =>
      expect(projections).toHaveBeenCalledWith(
        expect.objectContaining({ playerIds: [7], defenseIds: [33] }),
      ),
    );
  });

  it("stops at five players with a message", async () => {
    top.mockResolvedValue({
      source: "sleeper", scoring: "x", week: 3, total: 6,
      items: Array.from({ length: 6 }, (_, i) => entry({ id: i + 1, name: `Player ${i + 1}`, fantasy_points: 20 - i })),
    });
    const user = userEvent.setup();
    render(<StartPage />);
    for (let i = 1; i <= 5; i++) {
      await user.click(await screen.findByRole("button", { name: `Add Player ${i} to the comparison` }));
    }

    await user.click(screen.getByRole("button", { name: "Add Player 6 to the comparison" }));

    expect(screen.getByText(/compare up to 5 players/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove Player 6" })).not.toBeInTheDocument();
  });

  it("saves starred players to My Team, remembers them, and shows their projections", async () => {
    const user = await open();

    await user.click(screen.getByRole("button", { name: "Save Jahmyr Gibbs to My Team" }));
    expect(JSON.parse(window.localStorage.getItem("fantasyiq.myTeam.NFL")!)).toEqual([{ kind: "player", id: 1 }]);

    await user.click(screen.getByRole("tab", { name: /My team/ }));
    expect(await screen.findByRole("button", { name: "Add Jahmyr Gibbs to the comparison" })).toBeInTheDocument();
    expect(projections).toHaveBeenCalledWith(expect.objectContaining({ playerIds: [1] }));
  });

  it("says so when My Team is empty", async () => {
    const user = await open();

    await user.click(screen.getByRole("tab", { name: /My team/ }));

    expect(screen.getByText(/Star players/)).toBeInTheDocument();
  });

  it("reports a failure to load the list", async () => {
    top.mockRejectedValue(new Error("Failed to list top players (502): Sleeper could not be reached"));
    render(<StartPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Sleeper could not be reached");
  });

  it("switches to the NBA with its own slots and no weeks", async () => {
    const user = await open();

    await user.click(screen.getByRole("button", { name: "NBA" }));

    expect(await screen.findByRole("button", { name: "Util" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: "Next week" })).not.toBeInTheDocument();
    await waitFor(() => expect(top).toHaveBeenLastCalledWith(expect.objectContaining({ sport: "NBA", slot: "UTIL" })));
    expect(within(screen.getByLabelText("Scoring")).getAllByRole("option").map((o) => o.textContent)).toEqual(["FantasyIQ", "Custom"]);
  });

  it("remembers edited scoring weights and switches to Custom", async () => {
    const user = await open();
    await user.click(screen.getByRole("button", { name: "Sources and scoring settings" }));

    const reception = screen.getByLabelText("Reception");
    await user.clear(reception);
    await user.type(reception, "0.75");

    expect(screen.getByLabelText("Scoring")).toHaveValue("custom");
    expect(JSON.parse(window.localStorage.getItem("fantasyiq.customScoring.NFL")!)).toEqual({ receptions: 0.75 });
    await waitFor(() =>
      expect(top).toHaveBeenLastCalledWith(
        expect.objectContaining({ scoring: expect.objectContaining({ name: "Custom" }) }),
      ),
    );
  });

  describe("the custom scoring fields follow the scoring choice", () => {
    async function receptionAfter(user: ReturnType<typeof userEvent.setup>, choice: string) {
      await user.selectOptions(screen.getByLabelText("Scoring"), choice);
      return (screen.getByLabelText("Reception") as HTMLInputElement).value;
    }

    it("shows 1, 0.5 and 0 for PPR, Half-PPR and Standard", async () => {
      const user = await open();
      await user.click(screen.getByRole("button", { name: "Sources and scoring settings" }));

      expect((screen.getByLabelText("Reception") as HTMLInputElement).value).toBe("1");
      expect(await receptionAfter(user, "Half-PPR")).toBe("0.5");
      expect(await receptionAfter(user, "Standard")).toBe("0");
      expect(await receptionAfter(user, "FantasyIQ (PPR)")).toBe("1");
    });

    it("keeps the picked scoring's reception value when moving to Custom, and remembers it", async () => {
      const user = await open();
      await user.click(screen.getByRole("button", { name: "Sources and scoring settings" }));

      await user.selectOptions(screen.getByLabelText("Scoring"), "Half-PPR");
      await user.selectOptions(screen.getByLabelText("Scoring"), "Custom");

      expect((screen.getByLabelText("Reception") as HTMLInputElement).value).toBe("0.5");
      expect(JSON.parse(window.localStorage.getItem("fantasyiq.customScoring.NFL")!).receptions).toBe(0.5);
    });

    it("editing another weight under Half-PPR keeps the half point per reception", async () => {
      const user = await open();
      await user.click(screen.getByRole("button", { name: "Sources and scoring settings" }));
      await user.selectOptions(screen.getByLabelText("Scoring"), "Half-PPR");

      const yards = screen.getByLabelText("Passing yard");
      await user.clear(yards);
      await user.type(yards, "0.05");

      expect(screen.getByLabelText("Scoring")).toHaveValue("custom");
      await waitFor(() => {
        const last = top.mock.calls[top.mock.calls.length - 1][0];
        expect(last.scoring?.name).toBe("Custom");
        expect(last.scoring?.player_weights).toEqual(
          expect.objectContaining({ receptions: 0.5, passing_yards: 0.05 }),
        );
      });
    });

    it("does not show stale saved custom weights while a preset is selected", async () => {
      window.localStorage.setItem("fantasyiq.customScoring.NFL", JSON.stringify({ receptions: 3 }));
      const user = await open();
      await user.click(screen.getByRole("button", { name: "Sources and scoring settings" }));

      expect(screen.getByLabelText("Scoring")).toHaveValue("default");
      expect((screen.getByLabelText("Reception") as HTMLInputElement).value).toBe("1");
    });
  });

  describe("paging through the top players", () => {
    const everyone = Array.from({ length: 32 }, (_, i) =>
      entry({ id: i + 1, name: `Quarterback ${i + 1}`, position: "QB", fantasy_points: 32 - i }),
    );

    beforeEach(() => {
      top.mockImplementation(async (query) => {
        const from = query.offset ?? 0;
        return {
          source: "sleeper",
          scoring: "x",
          week: 3,
          items: everyone.slice(from, from + (query.limit ?? 30)),
          total: everyone.length,
        };
      });
    });

    it("shows thirty at a time, says how many there are, and asks for thirty per page", async () => {
      render(<StartPage />);

      expect(await screen.findByText("Showing 1–30 of 32")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Add Quarterback 30 to the comparison" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Add Quarterback 31 to the comparison" })).not.toBeInTheDocument();
      expect(top).toHaveBeenCalledWith(expect.objectContaining({ limit: 30, offset: 0 }));
    });

    it("moves to the next thirty and back, numbering the ranks from where the page starts", async () => {
      const user = userEvent.setup();
      render(<StartPage />);
      await screen.findByText("Showing 1–30 of 32");
      expect(screen.getByRole("button", { name: /Previous 30/ })).toBeDisabled();

      await user.click(screen.getByRole("button", { name: /Next 30/ }));

      expect(await screen.findByText("Showing 31–32 of 32")).toBeInTheDocument();
      expect(top).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 30 }));
      expect(screen.getByRole("button", { name: "Add Quarterback 31 to the comparison" })).toBeInTheDocument();
      expect(screen.getByText("31.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Next 30/ })).toBeDisabled();

      await user.click(screen.getByRole("button", { name: /Previous 30/ }));
      expect(await screen.findByText("Showing 1–30 of 32")).toBeInTheDocument();
    });

    it("starts again from the first page when the list changes", async () => {
      const user = userEvent.setup();
      render(<StartPage />);
      await user.click(await screen.findByRole("button", { name: /Next 30/ }));
      await screen.findByText("Showing 31–32 of 32");

      await user.click(screen.getByRole("button", { name: "QB" }));

      await waitFor(() => expect(top).toHaveBeenLastCalledWith(expect.objectContaining({ slot: "QB", offset: 0 })));
      expect(await screen.findByText("Showing 1–30 of 32")).toBeInTheDocument();
    });

    it("has no page buttons when there is nothing to page", async () => {
      top.mockResolvedValue({ source: "sleeper", scoring: "x", week: 3, items: [], total: 0 });
      render(<StartPage />);

      expect(await screen.findByText("No projections for this slot yet.")).toBeInTheDocument();
      expect(screen.queryByRole("navigation", { name: "Pages of players" })).not.toBeInTheDocument();
    });
  });

  describe("players whose game has started", () => {
    const over = { ...gibbs.game!, status: "final" as const };
    const played = entry({ id: 1, name: "Jahmyr Gibbs", fantasy_points: 30, game: over });

    it("stay in the top list, marked Final", async () => {
      respond([played, lamb]);
      render(<StartPage />);

      const row = await screen.findByRole("button", { name: "Add Jahmyr Gibbs to the comparison" });

      expect(row).toHaveTextContent("Final");
      expect(screen.getByRole("button", { name: "Add CeeDee Lamb to the comparison" })).not.toHaveTextContent("Final");
    });

    it("can be compared but never recommended, with a clear game-over highlight", async () => {
      respond([played, lamb, chase]);
      projections.mockImplementation(async (query) => ({
        source: "sleeper",
        scoring: "FantasyIQ",
        week: 3,
        total: null,
        items: [played, lamb].filter((e) => (query.playerIds ?? []).includes(e.id)),
      }));
      const user = userEvent.setup();
      render(<StartPage />);
      await user.click(await screen.findByRole("button", { name: "Add Jahmyr Gibbs to the comparison" }));
      await user.click(screen.getByRole("button", { name: "Add CeeDee Lamb to the comparison" }));

      await user.click(screen.getByRole("button", { name: "View advice" }));

      expect(await screen.findByRole("heading", { name: "Start CeeDee Lamb" })).toBeInTheDocument();
      const advice = screen.getByRole("region", { name: "Start/sit advice" });
      expect(within(advice).getByText(/Game over: can.t be started/)).toBeInTheDocument();
      expect(within(advice).getByText(/Jahmyr Gibbs can't be started/)).toBeInTheDocument();
      expect(within(advice).getByText("Final")).toBeInTheDocument();
      expect(within(advice).getAllByText("Start")).toHaveLength(1);
      expect(within(advice).queryByText("Sit")).not.toBeInTheDocument();
    });

    it("say so when nobody in the comparison can be started", async () => {
      const alsoOver = entry({ id: 2, name: "CeeDee Lamb", fantasy_points: 18, game: over });
      respond([played, alsoOver]);
      projections.mockResolvedValue({ source: "sleeper", scoring: "x", week: 3, total: null, items: [played, alsoOver] });
      const user = userEvent.setup();
      render(<StartPage />);
      await user.click(await screen.findByRole("button", { name: "Add Jahmyr Gibbs to the comparison" }));
      await user.click(screen.getByRole("button", { name: "Add CeeDee Lamb to the comparison" }));

      await user.click(screen.getByRole("button", { name: "View advice" }));

      expect(await screen.findByRole("heading", { name: "Nobody here can be started" })).toBeInTheDocument();
    });
  });

  describe("remembering the comparison", () => {
    it("puts the comparison in the address as you go", async () => {
      const user = await open();

      await user.click(screen.getByRole("button", { name: "Add Jahmyr Gibbs to the comparison" }));
      await user.click(screen.getByRole("button", { name: "Add CeeDee Lamb to the comparison" }));
      await user.click(screen.getByRole("button", { name: "View advice" }));
      await user.click(screen.getByRole("button", { name: "WR" }));
      await user.click(screen.getByRole("button", { name: "Next week" }));

      await waitFor(() => expect(window.location.search).toBe("?slot=WR&week=4&picks=p1,p2&advice=1"));
    });

    it("restores the players, slot, week, scoring and the open advice from the address", async () => {
      window.history.replaceState(null, "", "/start?slot=WR&week=5&scoring=half&picks=p1,p2&advice=1");
      render(<StartPage />);

      expect(await screen.findByRole("heading", { name: "Start Jahmyr Gibbs" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Remove Jahmyr Gibbs" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Remove CeeDee Lamb" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "WR" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByLabelText("Scoring")).toHaveValue("half");
      await waitFor(() =>
        expect(top).toHaveBeenCalledWith(expect.objectContaining({ slot: "WR", week: 5 })),
      );
      // the list is never fetched for the defaults first and then again for the restored state
      expect(top).not.toHaveBeenCalledWith(expect.objectContaining({ slot: "FLEX" }));
    });

    it("keeps the players in the order they were in the address", async () => {
      window.history.replaceState(null, "", "/start?picks=p3,p1,p2");
      render(<StartPage />);

      await screen.findByRole("button", { name: "Remove Ja'Marr Chase" });
      const names = screen
        .getAllByRole("button", { name: /^Remove / })
        .map((b) => b.getAttribute("aria-label"))
        .filter((label) => !label?.includes("from the comparison"));
      expect(names).toEqual(["Remove Ja'Marr Chase", "Remove Jahmyr Gibbs", "Remove CeeDee Lamb"]);
    });

    it("picks up where you left off when opened without an address", async () => {
      window.localStorage.setItem("fantasyiq.start.last", "slot=TE&picks=p1,p2");
      render(<StartPage />);

      expect(await screen.findByRole("button", { name: "Remove Jahmyr Gibbs" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "TE" })).toHaveAttribute("aria-pressed", "true");
    });

    it("prefers the address over the last visit, and ignores invalid values in it", async () => {
      window.localStorage.setItem("fantasyiq.start.last", "slot=TE");
      window.history.replaceState(null, "", "/start?slot=NOPE&week=99&picks=zzz");
      render(<StartPage />);

      expect(await screen.findByRole("button", { name: "FLEX" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
    });

    it("says so when the players can't be restored", async () => {
      window.history.replaceState(null, "", "/start?picks=p1,p2");
      projections.mockRejectedValue(new Error("boom"));
      render(<StartPage />);

      expect(await screen.findByText(/Couldn.t restore your players/)).toBeInTheDocument();
    });

    it("restores the NBA with its own slots", async () => {
      window.history.replaceState(null, "", "/start?sport=NBA&slot=G");
      render(<StartPage />);

      expect(await screen.findByRole("button", { name: "G" })).toHaveAttribute("aria-pressed", "true");
      await waitFor(() => expect(top).toHaveBeenCalledWith(expect.objectContaining({ sport: "NBA", slot: "G" })));
    });
  });
});
