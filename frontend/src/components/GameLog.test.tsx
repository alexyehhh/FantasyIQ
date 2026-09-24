import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GameLog, { describeScoring } from "./GameLog";
import { buildLogRows } from "@/lib/gameLog";
import {
  makeEntry,
  makeNbaGames,
  makeScheduleEntry,
  makeTeam,
  makeUpcoming,
  scheduleFromGames,
} from "@/test/fixtures";

/** Rows for a season in which the player has these results (newest first) and these games to come. */
function rowsFor(played = makeNbaGames(0), upcoming = makeUpcoming(0), byeWeek: number | null = null) {
  return buildLogRows(played, [...scheduleFromGames(played), ...upcoming], byeWeek);
}

const bodyRows = () => Array.from(screen.getByRole("table").querySelectorAll("tbody tr"));

describe("GameLog", () => {
  it("lists every game when they fit on one page, with no paging buttons", () => {
    render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(3), makeUpcoming(14))} selectedStat="points" />);

    expect(bodyRows()).toHaveLength(17);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("3 played · 14 upcoming")).toBeInTheDocument();
  });

  it("shows the opponent, home/away and the score from the player's side", () => {
    const entries = [
      makeEntry({
        game_id: 2,
        opponent: makeTeam({ abbreviation: "LAL" }),
        is_home: true,
        team_score: 110,
        opponent_score: 104,
        result: "W",
      }),
      makeEntry({
        game_id: 1,
        game_date: "2026-01-03T18:00:00Z",
        opponent: makeTeam({ abbreviation: "BOS" }),
        is_home: false,
        team_score: 99,
        opponent_score: 101,
        result: "L",
      }),
    ];
    render(<GameLog sport="NBA" rows={rowsFor(entries)} selectedStat="points" />);

    expect(screen.getByText("vs LAL")).toBeInTheDocument();
    expect(screen.getByText("@ BOS")).toBeInTheDocument();
    expect(screen.getByText("W")).toHaveClass("text-good");
    expect(screen.getByText("110–104")).toBeInTheDocument();
    expect(screen.getByText("L")).toHaveClass("text-bad");
  });

  it("puts results before upcoming games, in date order", () => {
    render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(2), makeUpcoming(2))} selectedStat="points" />);

    const rows = bodyRows();
    expect(rows[0]).toHaveTextContent("Jan 29");
    expect(rows[1]).toHaveTextContent("Jan 30");
    expect(rows[2]).toHaveTextContent("Upcoming");
    expect(rows[3]).toHaveTextContent("Upcoming");
  });

  it("shows an upcoming game's opponent and Pacific kickoff time where a result would be", () => {
    const upcoming = [
      makeScheduleEntry({
        game_date: "2999-01-05T18:00:00Z", // 10:00 AM Pacific
        is_home: false,
        opponent: makeTeam({ abbreviation: "BOS" }),
      }),
    ];
    render(<GameLog sport="NBA" rows={rowsFor([], upcoming)} selectedStat="points" />);

    const [row] = bodyRows();
    expect(row).toHaveTextContent("@ BOS");
    expect(row).toHaveTextContent("10:00 AM");
    expect(row).not.toHaveTextContent("ET");
  });

  it("marks a game in progress as live", () => {
    const rows = rowsFor([], [makeScheduleEntry({ status: "in_progress" })]);
    render(<GameLog sport="NBA" rows={rows} selectedStat="points" />);

    expect(bodyRows()[0]).toHaveTextContent("Live");
    expect(bodyRows()[0]).toHaveTextContent("In progress");
  });

  it("notes a played game with no stat line", () => {
    const rows = rowsFor([], [makeScheduleEntry({ status: "final", result: "W", team_score: 90, opponent_score: 80 })]);
    render(<GameLog sport="NBA" rows={rows} selectedStat="points" />);

    expect(bodyRows()[0]).toHaveTextContent("No stats recorded");
  });

  it("shows a dash where the opponent or result isn't known", () => {
    render(<GameLog sport="NBA" rows={rowsFor([makeEntry()])} selectedStat="points" />);

    expect(screen.getAllByText("—")).toHaveLength(2); // opponent and result
  });

  it("highlights the best game in the selected stat's column", () => {
    const entries = [
      makeEntry({ game_id: 2, game_date: "2026-01-06T18:00:00Z", stats: { points: 12, assists: 2 } }),
      makeEntry({ game_id: 1, stats: { points: 31, assists: 2 } }),
    ];
    render(<GameLog sport="NBA" rows={rowsFor(entries)} selectedStat="points" />);

    // (assists differ from points, so no other column repeats these numbers)
    expect(screen.getByRole("cell", { name: "31" })).toHaveClass("text-accent");
    expect(screen.getByRole("cell", { name: "12" })).not.toHaveClass("text-accent");
  });

  it("shows fantasy points as the last column", () => {
    const entries = [makeEntry({ stats: { points: 10, assists: 2 } })];
    render(<GameLog sport="NBA" rows={rowsFor(entries)} selectedStat="points" />);

    expect(screen.getByRole("columnheader", { name: "FPTS" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "13" })).toHaveClass("font-bold");
  });

  it("groups NFL columns, labels the week, and dims stats a player didn't record", () => {
    const entries = [makeEntry({ week: 3, stats: { receptions: 5, receiving_yards: 61 } })];
    render(<GameLog sport="NFL" rows={rowsFor(entries)} selectedStat="receiving_yards" />);

    for (const group of ["Passing", "Rushing", "Receiving", "Misc"]) {
      expect(screen.getByRole("columnheader", { name: group })).toBeInTheDocument();
    }
    expect(screen.getByText("Wk 3")).toBeInTheDocument();
    expect(screen.getAllByText("–").length).toBeGreaterThan(5);
    expect(screen.getByRole("cell", { name: "61" })).toHaveClass("text-accent");
  });

  it("shows the bye week between the weeks either side of it", () => {
    const upcoming = [4, 6].map((week, index) =>
      makeScheduleEntry({
        game_id: index + 1,
        week,
        game_date: `2999-10-${String(index + 4).padStart(2, "0")}T18:00:00Z`,
      }),
    );
    render(<GameLog sport="NFL" rows={rowsFor([], upcoming, 5)} selectedStat="receiving_yards" />);

    const rows = bodyRows();
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Wk 4");
    expect(rows[1]).toHaveTextContent("Week 5 · Bye");
    expect(rows[2]).toHaveTextContent("Wk 6");
  });

  it("explains how fantasy points were scored", () => {
    render(<GameLog sport="NBA" rows={rowsFor([makeEntry()])} selectedStat="points" />);

    expect(screen.getByText(/FPTS uses FantasyIQ standard scoring/)).toBeInTheDocument();
  });

  it("is just the schedule, with no stat columns or scoring note, when stats aren't shown", () => {
    render(
      <GameLog sport="NFL" rows={rowsFor([], makeUpcoming(2))} selectedStat="fpts" showStats={false} />,
    );

    expect(screen.queryByRole("columnheader", { name: "FPTS" })).not.toBeInTheDocument();
    expect(screen.queryByText(/FPTS uses/)).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Opp" })).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(2);
  });

  describe("paging a long season", () => {
    // Counted from the season's first game, in pages of 20: games 1-20, 21-40, ...
    const dates = () => bodyRows().map((row) => row.querySelector("td")!.textContent);
    const upcomingCount = () =>
      bodyRows().filter((row) => /Upcoming/.test(row.textContent ?? "")).length;

    it("starts at the season's first game, with no earlier page to go back to", () => {
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(3), makeUpcoming(80))} selectedStat="points" />);

      expect(bodyRows()).toHaveLength(20);
      expect(bodyRows()[0]).toHaveTextContent("Jan 28"); // the season's first game
      expect(screen.getByText("Games 1–20 of 83")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "‹ Previous 20" })).toBeDisabled();
      expect(upcomingCount()).toBe(17); // 3 results, then what's coming
    });

    it("only offers games from this season: last season's stat lines aren't listed", () => {
      // Ten old results that are not on this season's schedule, plus a full upcoming schedule.
      render(<GameLog sport="NBA" rows={buildLogRows(makeNbaGames(10), makeUpcoming(80), null)} selectedStat="points" />);

      expect(screen.getByText("0 played · 80 upcoming")).toBeInTheDocument();
      expect(screen.getByText("Games 1–20 of 80")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "‹ Previous 20" })).toBeDisabled();
      expect(upcomingCount()).toBe(20);
    });

    it("replaces the page with the next 20 rather than adding to it", async () => {
      const user = userEvent.setup();
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(3), makeUpcoming(80))} selectedStat="points" />);
      const firstPage = dates();

      await user.click(screen.getByRole("button", { name: "Next 20 ›" }));

      const secondPage = dates();
      expect(secondPage).toHaveLength(20);
      expect(secondPage.filter((date) => firstPage.includes(date))).toEqual([]);
      expect(screen.getByText("Games 21–40 of 83")).toBeInTheDocument();
    });

    it("jumps to the top of the game log when Next or Previous is pressed", async () => {
      const user = userEvent.setup();
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(3), makeUpcoming(80))} selectedStat="points" />);
      const scroll = Element.prototype.scrollIntoView as jest.Mock;
      scroll.mockClear();

      await user.click(screen.getByRole("button", { name: "Next 20 ›" }));
      expect(scroll).toHaveBeenCalledTimes(1);
      expect(scroll.mock.instances[0]).toBe(screen.getByLabelText("Game log"));
      expect(scroll).toHaveBeenLastCalledWith({ block: "start" });

      await user.click(screen.getByRole("button", { name: "‹ Previous 20" }));
      expect(scroll).toHaveBeenCalledTimes(2);
      expect(scroll.mock.instances[1]).toBe(screen.getByLabelText("Game log"));
    });

    it("doesn't scroll just because the log was shown", () => {
      const scroll = Element.prototype.scrollIntoView as jest.Mock;
      scroll.mockClear();

      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(3), makeUpcoming(80))} selectedStat="points" />);

      expect(scroll).not.toHaveBeenCalled();
    });

    it("goes back with Previous, restoring exactly the page that was left", async () => {
      const user = userEvent.setup();
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(3), makeUpcoming(80))} selectedStat="points" />);
      const firstPage = dates();
      await user.click(screen.getByRole("button", { name: "Next 20 ›" }));

      await user.click(screen.getByRole("button", { name: "‹ Previous 20" }));

      expect(dates()).toEqual(firstPage);
    });

    it("moves on to the next 20 by default once the first 20 are all played", () => {
      // 25 results, so games 1-20 are complete and the log opens on games 21-40.
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(25), makeUpcoming(57))} selectedStat="points" />);

      expect(screen.getByText("Games 21–40 of 82")).toBeInTheDocument();
      expect(bodyRows().filter((row) => !/Upcoming/.test(row.textContent ?? ""))).toHaveLength(5);
      expect(screen.getByRole("button", { name: "‹ Previous 20" })).toBeEnabled();
    });

    it("stays on the first 20 while any of them is still to come", () => {
      // 19 results: game 20 is still upcoming, so the first page is not yet full.
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(19), makeUpcoming(63))} selectedStat="points" />);

      expect(screen.getByText("Games 1–20 of 82")).toBeInTheDocument();
    });

    it("moves on exactly when the 20th game has been played", () => {
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(20), makeUpcoming(62))} selectedStat="points" />);

      expect(screen.getByText("Games 21–40 of 82")).toBeInTheDocument();
    });

    it("pages to the end, where the last page is short and Next is off", async () => {
      const user = userEvent.setup();
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(0), makeUpcoming(45))} selectedStat="points" />);

      await user.click(screen.getByRole("button", { name: "Next 20 ›" }));
      await user.click(screen.getByRole("button", { name: "Next 5 ›" }));

      expect(screen.getByText("Games 41–45 of 45")).toBeInTheDocument();
      expect(bodyRows()).toHaveLength(5);
      expect(screen.getByRole("button", { name: "Next 20 ›" })).toBeDisabled();
    });

    it("opens on the last page when the season is over", () => {
      render(<GameLog sport="NBA" rows={rowsFor(makeNbaGames(30))} selectedStat="points" />);

      expect(screen.getByText("Games 21–30 of 30")).toBeInTheDocument();
      expect(bodyRows()).toHaveLength(10);
      expect(screen.getByRole("button", { name: "Next 20 ›" }).textContent).toBe("Next 20 ›");
      expect(screen.getByRole("button", { name: "Next 20 ›" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "‹ Previous 20" })).toBeEnabled();
    });

    it("shows a whole 17-game football season without paging", () => {
      const season = Array.from({ length: 17 }, (_, index) =>
        makeScheduleEntry({ game_id: index + 1, week: index + 1, game_date: `2999-09-${String(index + 1).padStart(2, "0")}T18:00:00Z` }),
      );
      render(<GameLog sport="NFL" rows={rowsFor([], season, null)} selectedStat="fpts" />);

      expect(bodyRows()).toHaveLength(17);
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(screen.queryByText(/Games \d+–\d+ of/)).not.toBeInTheDocument();
    });
  });
});

describe("describeScoring", () => {
  it("lists each weight, with a real minus sign for penalties", () => {
    const text = describeScoring("NFL");

    expect(text).toContain("Interceptions −2");
    expect(text).toContain("Receptions +1");
  });
});
