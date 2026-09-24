import { render, screen, within } from "@testing-library/react";
import DefenseHero from "./DefenseHero";
import { makeDefenseDetail, makeDefenseEntry, makeTeam } from "@/test/fixtures";

describe("DefenseHero", () => {
  it("shows the team, D/ST, its abbreviation and its bye week", () => {
    render(<DefenseHero defense={makeDefenseDetail()} entries={[]} />);

    expect(screen.getByRole("heading", { name: "Cincinnati Bengals" })).toBeInTheDocument();
    expect(screen.getByText("CIN · NFL")).toBeInTheDocument();
    expect(screen.getByText("D/ST")).toBeInTheDocument();
    expect(screen.getByText("Bye week 6")).toBeInTheDocument();
  });

  it("leaves out the bye week when the team has none", () => {
    render(<DefenseHero defense={makeDefenseDetail({ bye_week: null })} entries={[]} />);

    expect(screen.queryByText(/Bye week/)).not.toBeInTheDocument();
  });

  it("puts the next game in the header", () => {
    const defense = makeDefenseDetail({
      next_game: {
        game_id: 9,
        start_time: "2026-09-27T17:00:00Z",
        status: "scheduled",
        is_home: false,
        opponent: makeTeam({ name: "Pittsburgh Steelers", abbreviation: "PIT" }),
      },
    });
    render(<DefenseHero defense={defense} entries={[]} />);

    expect(screen.getByLabelText("Next game")).toHaveTextContent("@ Pittsburgh Steelers");
  });

  it("averages the last ten games for fantasy points and the four defense stats", () => {
    const entries = [
      makeDefenseEntry({ game_id: 2, fantasy_points: 20, stats: { ...makeDefenseEntry().stats, sacks: 6 } }),
      makeDefenseEntry({ game_id: 1, fantasy_points: 12, stats: { ...makeDefenseEntry().stats, sacks: 2 } }),
    ];
    render(<DefenseHero defense={makeDefenseDetail()} entries={entries} />);

    const fpts = screen.getByRole("group", { name: "Fantasy pts" });
    expect(within(fpts).getByText("16")).toBeInTheDocument();
    const sacks = screen.getByRole("group", { name: "Sacks" });
    expect(within(sacks).getByText("4")).toBeInTheDocument();
    for (const name of ["Interceptions", "Points allowed", "Yards allowed"]) {
      expect(screen.getByRole("group", { name })).toBeInTheDocument();
    }
  });

  it("counts a rise in points allowed as bad news, and a rise in sacks as good", () => {
    // Most recent first: five recent games are worse on points allowed and better on sacks.
    const games = [1, 2, 3, 4, 5, 6].map((id) =>
      makeDefenseEntry({
        game_id: id,
        stats: {
          ...makeDefenseEntry().stats,
          points_allowed: id <= 5 ? 30 : 10,
          sacks: id <= 5 ? 5 : 1,
        },
      }),
    );
    render(<DefenseHero defense={makeDefenseDetail()} entries={games} />);

    const badge = (name: string) =>
      within(screen.getByRole("group", { name })).getByText(/▲|▼/);
    expect(badge("Points allowed")).toHaveClass("text-bad");
    expect(badge("Sacks")).toHaveClass("text-good");
  });
});
