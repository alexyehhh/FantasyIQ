import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StatChart from "./StatChart";
import type { PlayerGameStatsEntry } from "@/lib/api";

const nbaEntries: PlayerGameStatsEntry[] = [
  {
    game_id: 2,
    game_date: "2026-01-10T00:00:00Z",
    stats: { points: 30, rebounds: 5, assists: 7 },
  },
  {
    game_id: 1,
    game_date: "2026-01-05T00:00:00Z",
    stats: { points: 22, rebounds: 8, assists: 4 },
  },
];

describe("StatChart", () => {
  it("shows a fallback message when there are no game stats", () => {
    render(<StatChart sport="NBA" entries={[]} />);
    expect(screen.getByText("No game stats yet.")).toBeInTheDocument();
  });

  it("defaults to the sport's preferred stat and lists all available stats as options", () => {
    render(<StatChart sport="NBA" entries={nbaEntries} />);

    const select = screen.getByLabelText("Stat") as HTMLSelectElement;
    expect(select.value).toBe("points");
    expect(screen.getByRole("option", { name: "rebounds" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "assists" })).toBeInTheDocument();
  });

  it("switches the charted stat when a different option is selected", async () => {
    const user = userEvent.setup();
    render(<StatChart sport="NBA" entries={nbaEntries} />);

    const select = screen.getByLabelText("Stat") as HTMLSelectElement;
    await user.selectOptions(select, "assists");

    expect(select.value).toBe("assists");
  });

  it("falls back to the first stat key when the sport has no preferred stat present", () => {
    const entries: PlayerGameStatsEntry[] = [
      { game_id: 1, game_date: "2026-01-05T00:00:00Z", stats: { fumbles_lost: 1 } },
    ];
    render(<StatChart sport="NFL" entries={entries} />);

    const select = screen.getByLabelText("Stat") as HTMLSelectElement;
    expect(select.value).toBe("fumbles_lost");
  });
});
