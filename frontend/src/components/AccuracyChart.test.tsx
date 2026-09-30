import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AccuracyChart from "./AccuracyChart";
import { makeAccuracyResponse } from "@/test/fixtures";

describe("AccuracyChart", () => {
  it("has a legend naming every source with its overall average miss", () => {
    render(<AccuracyChart report={makeAccuracyResponse()} />);

    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("FantasyIQ model")).toBeInTheDocument();
    expect(within(legend).getByText("avg 4.4")).toBeInTheDocument();
    expect(within(legend).getByText("Sleeper")).toBeInTheDocument();
    expect(within(legend).getByText("avg 5.0")).toBeInTheDocument();
  });

  it("describes the chart in words for anyone who can't see it", () => {
    render(<AccuracyChart report={makeAccuracyResponse()} />);

    expect(
      screen.getByRole("img", {
        name: "Average miss in fantasy points by week for FantasyIQ model 4.4, Sleeper 5.0",
      }),
    ).toBeInTheDocument();
  });

  it("offers the same numbers as a table, with the sample behind each week", async () => {
    render(<AccuracyChart report={makeAccuracyResponse()} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Show table" }));

    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3); // header + two weeks
    expect(within(rows[1]).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
      "120",
      "4.6",
      "5.1",
    ]);
    expect(screen.getByRole("button", { name: "Show chart" })).toHaveAttribute("aria-pressed", "true");
  });
});
