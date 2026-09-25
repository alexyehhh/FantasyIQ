import { render, screen, within } from "@testing-library/react";
import DefenseHero from "./DefenseHero";
import { makeDefenseDetail, makeDefenseEntry, makeSeasonSummary, makeTeam } from "@/test/fixtures";

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

  it("shows dashes rather than last-10 averages without a season summary", () => {
    render(<DefenseHero defense={makeDefenseDetail()} entries={[]} />);

    const fpts = screen.getByRole("group", { name: "Fantasy pts" });
    expect(fpts).toHaveTextContent("Season");
    expect(fpts).toHaveTextContent("—");
    expect(fpts).toHaveTextContent("No games yet");
    expect(screen.queryByText(/L10|L5 vs all/)).not.toBeInTheDocument();
    for (const name of ["Sacks", "Interceptions", "Points allowed", "Yards allowed"]) {
      expect(screen.getByRole("group", { name })).toBeInTheDocument();
    }
  });

  it("shows season totals with the rank among the defenses, fewest allowed first", () => {
    const season = makeSeasonSummary({
      position_group: "DEF",
      stats: {
        fantasy_points: { total: 34, rank: 1, tied: false },
        sacks: { total: 8, rank: 2, tied: true },
        interceptions: { total: 0, rank: 24, tied: true },
        points_allowed: { total: 26, rank: 5, tied: false },
        yards_allowed: { total: 656, rank: 11, tied: false },
      },
    });
    render(<DefenseHero defense={makeDefenseDetail()} entries={[makeDefenseEntry()]} season={season} />);

    const fpts = screen.getByRole("group", { name: "Fantasy pts" });
    expect(fpts).toHaveTextContent("34");
    expect(fpts).toHaveTextContent("#1");
    expect(fpts).toHaveTextContent("of 32 DEF");
    expect(screen.getByRole("group", { name: "Sacks" })).toHaveTextContent("T-#2");
    expect(screen.getByRole("group", { name: "Points allowed" })).toHaveTextContent("26");
    expect(screen.getByRole("group", { name: "Points allowed" })).toHaveTextContent("Season");
  });
});
