import { render, screen } from "@testing-library/react";
import PlayerAccuracy from "./PlayerAccuracy";
import type { AccuracyPlayerGame } from "@/lib/api";

const game = (overrides: Partial<AccuracyPlayerGame> = {}): AccuracyPlayerGame => ({
  game_id: 1,
  player_id: 7,
  player_name: "Aaron Rodgers",
  position: "QB",
  team: "PIT",
  opponent: "CLE",
  home: false,
  season: "2026",
  week: 4,
  start_time: "2026-10-02T00:15:00",
  played: true,
  actual: 20,
  projected: { sleeper: 13.5, fantasyiq: 15.3 },
  ...overrides,
});

describe("PlayerAccuracy", () => {
  it("shows actual points, each projection and its miss, and who is closer on average", () => {
    render(<PlayerAccuracy games={[game()]} />);

    expect(screen.getByText("Week 4")).toBeInTheDocument();
    expect(screen.getByText("20.0")).toBeInTheDocument();
    expect(screen.getByText("15.3")).toBeInTheDocument();
    // With one game the average card repeats the row's numbers, so each shows up twice.
    expect(screen.getAllByText(/−4\.7/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/−6\.5/).length).toBeGreaterThan(0);
    expect(screen.getByText(/FantasyIQ model has been closer over 1 game/)).toBeInTheDocument();
  });

  it("marks a game the player missed and leaves it out of the average", () => {
    render(<PlayerAccuracy games={[game({ game_id: 2, week: 5, played: false, actual: null }), game()]} />);

    expect(screen.getByText("DNP")).toBeInTheDocument();
    expect(screen.getByText(/closer over 1 game\./)).toBeInTheDocument();
  });

  it("renders nothing for a player with no saved projections", () => {
    const { container } = render(<PlayerAccuracy games={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
