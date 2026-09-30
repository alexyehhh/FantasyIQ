import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AccuracyPage from "./page";
import { getAccuracy, getScoringPreset } from "@/lib/api";
import { makeAccuracyResponse, makeScoringConfig } from "@/test/fixtures";

jest.mock("@/lib/api", () => ({
  getAccuracy: jest.fn(),
  getScoringPreset: jest.fn(),
}));

const accuracy = jest.mocked(getAccuracy);
const preset = jest.mocked(getScoringPreset);

beforeEach(() => {
  jest.resetAllMocks();
  preset.mockResolvedValue(makeScoringConfig());
  accuracy.mockResolvedValue(makeAccuracyResponse());
});

describe("AccuracyPage", () => {
  it("says who is closer and shows the sample behind it", async () => {
    render(<AccuracyPage />);

    expect(await screen.findByText(/FantasyIQ model is closer/)).toBeInTheDocument();
    expect(screen.getByText(/240 player-games compared under FantasyIQ standard \(PPR\)/)).toBeInTheDocument();
    expect(screen.getByText(/7 projected players who didn't play aren't counted/)).toBeInTheDocument();
    expect(accuracy).toHaveBeenCalledWith({ sport: "NFL", position: null, scoring: null });
  });

  it("lists each position with a flag where there are too few games", async () => {
    render(<AccuracyPage />);

    const table = await screen.findByRole("table", { name: /Accuracy by position/ });
    const rows = within(table).getAllByRole("row");
    expect(within(rows[1]).getByRole("rowheader")).toHaveTextContent("RB");
    expect(within(rows[1]).getByRole("rowheader")).not.toHaveTextContent("few games");
    expect(within(rows[2]).getByRole("rowheader")).toHaveTextContent("TE");
    expect(within(rows[2]).getByRole("rowheader")).toHaveTextContent("few games");
  });

  it("explains an empty report instead of drawing an empty chart", async () => {
    accuracy.mockResolvedValue(
      makeAccuracyResponse({
        compared: 0,
        enough_data: false,
        overall: {},
        by_position: [],
        series: [],
        sources: [],
        coverage: {},
      }),
    );
    render(<AccuracyPage />);

    expect(await screen.findByText(/No finished games have saved projections yet/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("refetches for a position and for the other sport, dropping the position", async () => {
    render(<AccuracyPage />);
    await screen.findByText(/is closer/);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "RB" }));
    await waitFor(() =>
      expect(accuracy).toHaveBeenLastCalledWith({ sport: "NFL", position: "RB", scoring: null }),
    );

    await user.click(screen.getByRole("button", { name: "NBA" }));
    await waitFor(() =>
      expect(accuracy).toHaveBeenLastCalledWith({ sport: "NBA", position: null, scoring: null }),
    );
    expect(screen.getByRole("button", { name: "G" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "QB" })).not.toBeInTheDocument();
  });

  it("sends Half-PPR built from the sport's default scoring", async () => {
    render(<AccuracyPage />);
    await screen.findByText(/is closer/);

    await userEvent.setup().selectOptions(screen.getByLabelText("Scoring"), "half");

    await waitFor(() => {
      const last = accuracy.mock.calls.at(-1)?.[0];
      expect(last?.scoring?.name).toBe("Half-PPR");
      expect(last?.scoring?.player_weights.receptions).toBe(0.5);
    });
  });

  it("shows an error instead of nothing when the request fails", async () => {
    accuracy.mockRejectedValue(new Error("Failed to load projection accuracy (500)"));
    render(<AccuracyPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to load projection accuracy");
  });
});
