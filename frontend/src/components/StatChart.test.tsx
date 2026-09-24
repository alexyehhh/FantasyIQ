import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StatChart, { rangeOptions } from "./StatChart";
import { makeNbaGames } from "@/test/fixtures";

const STAT_OPTIONS = ["fpts", "points", "rebounds"];

function renderChart(overrides: Partial<React.ComponentProps<typeof StatChart>> = {}) {
  const props = {
    sport: "NBA" as const,
    entries: makeNbaGames(12),
    stat: "points",
    onStatChange: jest.fn(),
    statOptions: STAT_OPTIONS,
    range: 10 as const,
    onRangeChange: jest.fn(),
    ...overrides,
  };
  render(<StatChart {...props} />);
  return props;
}

describe("rangeOptions", () => {
  it("offers last 5, last 10 and all when there are more than 10 games", () => {
    expect(rangeOptions(20).map((o) => o.label)).toEqual(["Last 5", "Last 10", "All 20"]);
  });

  it("only offers ranges that are smaller than the games played", () => {
    expect(rangeOptions(8).map((o) => o.label)).toEqual(["Last 5", "All 8"]);
    expect(rangeOptions(3).map((o) => o.label)).toEqual(["All 3"]);
  });
});

describe("StatChart", () => {
  it("shows a chip for each stat with the charted one pressed", () => {
    renderChart();

    expect(screen.getByRole("button", { name: "Points" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Rebounds" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Fantasy pts" })).toBeInTheDocument();
  });

  it("reports the chosen stat when a chip is clicked", async () => {
    const props = renderChart();

    await userEvent.setup().click(screen.getByRole("button", { name: "Rebounds" }));

    expect(props.onStatChange).toHaveBeenCalledWith("rebounds");
  });

  it("reports the chosen range when a range button is clicked", async () => {
    const props = renderChart();

    await userEvent.setup().click(screen.getByRole("button", { name: "Last 5" }));

    expect(props.onRangeChange).toHaveBeenCalledWith(5);
  });

  it("shows the average of the games in the selected range", () => {
    // 12 games scoring 21..32, newest first: the last 5 are 28..32 (avg 30).
    renderChart({ range: 5 });

    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText(/Points per game · last 5/)).toBeInTheDocument();
  });

  it("hides the range control when there is only one range to show", () => {
    renderChart({ entries: makeNbaGames(3), range: "all" });

    expect(screen.queryByRole("group", { name: "Games shown" })).not.toBeInTheDocument();
  });

  it("describes the chart for screen readers", () => {
    renderChart({ range: 5 });

    expect(
      screen.getByRole("img", { name: "Points over 5 games, average 30" }),
    ).toBeInTheDocument();
  });
});
