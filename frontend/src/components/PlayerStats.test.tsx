import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlayerStats from "./PlayerStats";
import { makeEntry, makeNbaGames, makeUpcoming, scheduleFromGames } from "@/test/fixtures";

function renderStats(props: Partial<React.ComponentProps<typeof PlayerStats>> = {}) {
  return render(
    <PlayerStats
      sport="NBA"
      position="G"
      entries={makeNbaGames(12)}
      schedule={[]}
      byeWeek={null}
      {...props}
    />,
  );
}

describe("PlayerStats", () => {
  it("shows an empty state instead of empty charts when there are no games", () => {
    renderStats({ entries: [] });

    expect(screen.getByText("No game stats yet")).toBeInTheDocument();
    expect(screen.queryByLabelText("Game trend")).not.toBeInTheDocument();
  });

  it("still lists the schedule for a player who hasn't played yet", () => {
    renderStats({ entries: [], schedule: makeUpcoming(3) });

    expect(screen.getByText("No game stats yet")).toBeInTheDocument();
    expect(screen.getByLabelText("Game log")).toHaveTextContent("0 played · 3 upcoming");
  });

  it("explains that kickers aren't tracked, and shows only their schedule", () => {
    renderStats({ sport: "NFL", position: "PK", entries: [makeEntry()], schedule: makeUpcoming(2) });

    expect(screen.getByText("Stats aren't tracked for this position yet")).toBeInTheDocument();
    expect(screen.queryByLabelText("Game trend")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Averages")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Game log")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "FPTS" })).not.toBeInTheDocument();
  });

  it.each([
    ["NBA", "G", "Points"],
    ["NFL", "QB", "Passing yards"],
    ["NFL", "RB", "Rushing yards"],
    ["NFL", "WR", "Receiving yards"],
  ] as const)("charts %s %s by %s to start", (sport, position, chip) => {
    renderStats({
      sport,
      position,
      entries: [
        makeEntry({ stats: { points: 1, passing_yards: 1, rushing_yards: 1, receiving_yards: 1 } }),
      ],
    });

    expect(screen.getByRole("button", { name: chip })).toHaveAttribute("aria-pressed", "true");
  });

  it("makes the chart, averages and game log all follow the chosen stat", async () => {
    renderStats();
    const averages = screen.getByLabelText("Averages");
    const log = screen.getByLabelText("Game log");
    expect(within(averages).getByRole("row", { name: /^PTS/ })).toHaveClass("bg-accent-soft");

    await userEvent.setup().click(screen.getByRole("button", { name: "Rebounds" }));

    expect(screen.getByRole("button", { name: "Rebounds" })).toHaveAttribute("aria-pressed", "true");
    expect(within(averages).getByRole("row", { name: /^REB/ })).toHaveClass("bg-accent-soft");
    expect(within(averages).getByRole("row", { name: /^PTS/ })).not.toHaveClass("bg-accent-soft");
    expect(within(log).getByRole("columnheader", { name: "REB" })).toHaveClass("bg-accent-soft");
    expect(screen.getByLabelText("Consistency")).toHaveTextContent("Rebounds · 12 games");
  });

  it("adds upcoming games to the log without touching the averages", () => {
    renderStats({ schedule: [...scheduleFromGames(makeNbaGames(12)), ...makeUpcoming(5)] });

    expect(screen.getByLabelText("Game log")).toHaveTextContent("12 played · 5 upcoming");
    expect(within(screen.getByLabelText("Averages")).getByRole("columnheader", { name: "All 12" })).toBeInTheDocument();
    expect(screen.getByLabelText("Consistency")).toHaveTextContent("12 games");
  });

  it("keeps last season's games in the chart and averages but not in the game log", () => {
    // 12 games with stat lines, none of them on this season's (all upcoming) schedule.
    renderStats({ schedule: makeUpcoming(5) });

    expect(screen.getByLabelText("Game log")).toHaveTextContent("0 played · 5 upcoming");
    expect(within(screen.getByLabelText("Averages")).getByRole("columnheader", { name: "All 12" })).toBeInTheDocument();
    expect(screen.getByLabelText("Game trend")).toBeInTheDocument();
  });

  it("starts the chart on the last 10 games when more than 10 have been played", () => {
    renderStats({ entries: makeNbaGames(20) });

    expect(screen.getByRole("button", { name: "Last 10" })).toHaveAttribute("aria-pressed", "true");
  });

  it("starts the chart on all games when 10 or fewer have been played", () => {
    renderStats({ entries: makeNbaGames(4) });

    expect(screen.queryByRole("button", { name: /Last/ })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Game trend")).toHaveTextContent("all 4");
  });

  it("shows the whole-season averages table with L5, L10 and all-games columns", () => {
    renderStats();

    const averages = screen.getByLabelText("Averages");
    for (const heading of ["L5", "L10", "All 12"]) {
      expect(within(averages).getByRole("columnheader", { name: heading })).toBeInTheDocument();
    }
  });
});
