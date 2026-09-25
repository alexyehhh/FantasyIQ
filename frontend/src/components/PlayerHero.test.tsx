import { render, screen, within } from "@testing-library/react";
import PlayerHero from "./PlayerHero";
import {
  makeEntry,
  makeNbaGames,
  makePlayerDetail,
  makeSeasonSummary,
  makeTeam,
} from "@/test/fixtures";

describe("PlayerHero", () => {
  it("shows the player's identity: name, team, position, number and status", () => {
    render(<PlayerHero player={makePlayerDetail()} entries={[]} />);

    expect(screen.getByRole("heading", { name: "Steph Curry" })).toBeInTheDocument();
    expect(screen.getByText("Golden State Warriors · NBA")).toBeInTheDocument();
    expect(screen.getByText("G")).toBeInTheDocument();
    expect(screen.getByText("#30")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("no longer repeats the jersey number on the photo, or shows height, weight or age", () => {
    render(<PlayerHero player={makePlayerDetail()} entries={[]} />);

    expect(screen.getAllByText("#30")).toHaveLength(1);
    expect(screen.queryByText(/lbs/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Age /)).not.toBeInTheDocument();
  });

  it("shows the team's bye week instead", () => {
    const player = makePlayerDetail({
      sport: "NFL",
      position: "QB",
      team: makeTeam({ bye_week: 5 }),
    });
    render(<PlayerHero player={player} entries={[]} />);

    expect(screen.getByText("Bye week 5")).toBeInTheDocument();
  });

  it("shows no bye week for a team without one", () => {
    render(<PlayerHero player={makePlayerDetail()} entries={[]} />);

    expect(screen.queryByText(/Bye week/)).not.toBeInTheDocument();
  });

  it("writes a kicker's position as K and shows field goal tiles for them", () => {
    const player = makePlayerDetail({ sport: "NFL", position: "PK" });
    render(<PlayerHero player={player} entries={[]} />);

    expect(screen.getByText("K")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Fantasy pts" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Field goals made" })).toBeInTheDocument();
  });

  it("shows no stat tiles for a punter, whose stats aren't tracked", () => {
    const player = makePlayerDetail({ sport: "NFL", position: "P" });
    render(<PlayerHero player={player} entries={[]} />);

    expect(screen.queryByRole("group", { name: "Fantasy pts" })).not.toBeInTheDocument();
  });

  it("puts the next game in the header", () => {
    const player = makePlayerDetail({
      next_game: {
        game_id: 9,
        start_time: "2026-10-22T02:00:00Z",
        status: "scheduled",
        is_home: false,
        opponent: makeTeam({ name: "Los Angeles Lakers", abbreviation: "LAL" }),
      },
    });
    render(<PlayerHero player={player} entries={[]} />);

    const block = screen.getByLabelText("Next game");
    expect(block).toHaveTextContent("@ Los Angeles Lakers");
    // 02:00 UTC is 7:00 PM Pacific the evening before, and the zone isn't labelled.
    expect(block).toHaveTextContent("Wed, Oct 21 · 7:00 PM");
    expect(block).not.toHaveTextContent("ET");
  });

  it("marks a game that is underway", () => {
    const player = makePlayerDetail({
      next_game: {
        game_id: 9,
        start_time: "2026-10-22T02:00:00Z",
        status: "in_progress",
        is_home: true,
        opponent: makeTeam({ name: "Boston Celtics" }),
      },
    });
    render(<PlayerHero player={player} entries={[]} />);

    expect(screen.getByLabelText("Next game")).toHaveTextContent("Playing now");
  });

  it("says so when the team has nothing left on the schedule", () => {
    render(<PlayerHero player={makePlayerDetail()} entries={[]} />);

    expect(screen.getByLabelText("Next game")).toHaveTextContent("No upcoming games scheduled");
  });

  it("omits the next-game block for a player with no team", () => {
    render(<PlayerHero player={makePlayerDetail({ team: null, team_id: null })} entries={[]} />);

    expect(screen.queryByLabelText("Next game")).not.toBeInTheDocument();
    expect(screen.getByText("No team · NBA")).toBeInTheDocument();
  });

  it("shows the injury designation instead of Active", () => {
    render(
      <PlayerHero player={makePlayerDetail({ injury_status: "Questionable" })} entries={[]} />,
    );

    expect(screen.getByText("Questionable")).toBeInTheDocument();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });

  it("shows placeholders in the stat tiles until the player has played", () => {
    render(<PlayerHero player={makePlayerDetail()} entries={[]} />);

    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(5);
    expect(screen.getAllByText("No games yet")).toHaveLength(5);
  });

  it("shows an NBA player's season totals and rank among guards, with fantasy points first", () => {
    const season = makeSeasonSummary({
      position_group: "G",
      pool_size: 180,
      stats: {
        fantasy_points: { total: 1200.5, rank: 4, tied: false },
        points: { total: 1800, rank: 2, tied: false },
      },
    });
    render(<PlayerHero player={makePlayerDetail()} entries={makeNbaGames(12)} season={season} />);

    const tiles = screen.getByLabelText("Player summary");
    expect(tiles).toHaveTextContent("Fantasy pts");
    expect(tiles).toHaveTextContent("PTS · Season1800");
    expect(within(screen.getByRole("group", { name: "Points" })).getByText("#2")).toBeInTheDocument();
    expect(tiles).toHaveTextContent("of 180 G");
    expect(tiles).not.toHaveTextContent("L10");
  });

  it("uses the full stat name on NFL tiles", () => {
    const player = makePlayerDetail({ sport: "NFL", position: "WR" });
    render(<PlayerHero player={player} entries={[makeEntry({ stats: { receiving_yards: 90 } })]} />);

    expect(screen.getByText("Receiving yards")).toBeInTheDocument();
    expect(screen.getByText("Targets")).toBeInTheDocument();
  });

  describe("season totals and ranks", () => {
    const qb = () => makePlayerDetail({ sport: "NFL", position: "QB" });
    const tile = (name: string) => screen.getByRole("group", { name });

    it("shows each season total with its rank among the position under it", () => {
      render(<PlayerHero player={qb()} entries={[makeEntry()]} season={makeSeasonSummary()} />);

      expect(tile("Fantasy pts")).toHaveTextContent("41.5");
      expect(tile("Fantasy pts")).toHaveTextContent("#1");
      expect(tile("Passing yards")).toHaveTextContent("583");
      expect(tile("Passing yards")).toHaveTextContent("#3");
      expect(tile("Passing yards")).toHaveTextContent("of 32 QB");
      expect(tile("Rushing yards")).toHaveTextContent("40");
      expect(tile("Rushing yards")).toHaveTextContent("#7");
    });

    it("labels the tiles as season totals rather than last-10 averages", () => {
      render(<PlayerHero player={qb()} entries={[makeEntry()]} season={makeSeasonSummary()} />);

      expect(tile("Passing yards")).toHaveTextContent("Season");
      expect(tile("Passing yards")).not.toHaveTextContent("L10 avg");
      expect(screen.queryByText(/L5 vs all/)).not.toBeInTheDocument();
    });

    it("marks a tied rank, and highlights only the top five", () => {
      render(<PlayerHero player={qb()} entries={[makeEntry()]} season={makeSeasonSummary()} />);

      expect(tile("Passing TDs")).toHaveTextContent("T-#9");
      expect(within(tile("Passing yards")).getByText("#3")).toHaveClass("text-good");
      expect(within(tile("Rushing yards")).getByText("#7")).not.toHaveClass("text-good");
    });

    it("writes a kicker's group as K", () => {
      const kicker = makePlayerDetail({ sport: "NFL", position: "PK" });
      const season = makeSeasonSummary({
        position_group: "K",
        stats: {
          fantasy_points: { total: 31, rank: 1, tied: false },
          field_goals_made: { total: 6, rank: 1, tied: true },
          field_goal_attempts: { total: 6, rank: 1, tied: true },
          extra_points_made: { total: 5, rank: 11, tied: true },
          extra_point_attempts: { total: 5, rank: 12, tied: true },
        },
      });
      render(<PlayerHero player={kicker} entries={[makeEntry()]} season={season} />);

      expect(tile("Field goals made")).toHaveTextContent("T-#1");
      expect(tile("Field goals made")).toHaveTextContent("of 32 K");
    });

    it("shows dashes, not last-10 averages, without a season summary", () => {
      render(<PlayerHero player={makePlayerDetail()} entries={[]} season={null} />);

      expect(screen.getByRole("group", { name: "Fantasy pts" })).toHaveTextContent("Season");
      expect(screen.getByLabelText("Player summary")).not.toHaveTextContent("L10");
      expect(screen.queryByText(/L5 vs all/)).not.toBeInTheDocument();
      expect(screen.getAllByText("No games yet")).toHaveLength(5);
    });

    it("shows a dash for a tile the summary has no rank for", () => {
      const partial = makeSeasonSummary({
        stats: { fantasy_points: { total: 10, rank: 4, tied: false } },
      });
      render(<PlayerHero player={qb()} entries={[makeEntry()]} season={partial} />);

      expect(tile("Fantasy pts")).toHaveTextContent("10");
      expect(tile("Passing yards")).toHaveTextContent("—");
      expect(tile("Passing yards")).toHaveTextContent("Not ranked");
      expect(tile("Passing yards")).not.toHaveTextContent("L10");
    });
  });
});
