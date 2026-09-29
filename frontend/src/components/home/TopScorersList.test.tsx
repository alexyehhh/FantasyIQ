import { act, fireEvent, render, screen } from "@testing-library/react";
import TopScorersList, { ROTATE_MS } from "./TopScorersList";
import { getTopScorers } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/usePolling";
import { makeTopScorerEntry } from "@/test/fixtures";

jest.mock("@/lib/api", () => ({ getTopScorers: jest.fn() }));

const topScorers = jest.mocked(getTopScorers);

const gibbs = makeTopScorerEntry({ id: 1, name: "Jahmyr Gibbs", fantasy_points: 41.4 });
const smithNjigba = makeTopScorerEntry({
  id: 2,
  name: "Jaxon Smith-Njigba",
  position: "WR",
  fantasy_points: 35.4,
});

const tick = (ms = 0) => act(async () => jest.advanceTimersByTime(ms));

beforeEach(() => {
  jest.useFakeTimers();
  topScorers.mockReset();
  topScorers.mockResolvedValue({ items: [gibbs, smithNjigba], week: 3 });
});

afterEach(() => jest.useRealTimers());

describe("TopScorersList", () => {
  it("shows the leading scorer with their week, rank, and stat line", async () => {
    render(<TopScorersList />);
    await tick();

    expect(screen.getByText("Top scorers · Week 3")).toBeInTheDocument();
    expect(screen.getByText(/#1 of 2/)).toBeInTheDocument();
    expect(screen.getByText("Jahmyr Gibbs")).toBeInTheDocument();
    expect(screen.getByText("41.4")).toBeInTheDocument();
    expect(topScorers).toHaveBeenCalledWith("NFL", 25);
  });

  it("rotates to the next scorer automatically every 5 seconds, and loops back", async () => {
    render(<TopScorersList />);
    await tick();

    await tick(ROTATE_MS);
    expect(screen.getByText("Jaxon Smith-Njigba")).toBeInTheDocument();
    expect(screen.queryByText("Jahmyr Gibbs")).not.toBeInTheDocument();

    await tick(ROTATE_MS);
    expect(screen.getByText("Jahmyr Gibbs")).toBeInTheDocument();
  });

  it("jumps straight to a player when its dot is clicked", async () => {
    render(<TopScorersList />);
    await tick();

    fireEvent.click(screen.getByRole("tab", { name: "Jaxon Smith-Njigba" }));

    expect(screen.getByText("Jaxon Smith-Njigba")).toBeInTheDocument();
  });

  it("says so once no games have finished, and asks for the other sport on request", async () => {
    topScorers.mockResolvedValue({ items: [], week: null });
    render(<TopScorersList />);
    await tick();

    expect(screen.getByText(/No games have finished/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "NBA" }));
    await tick();

    expect(topScorers).toHaveBeenLastCalledWith("NBA", 25);
  });

  it("silently refetches every 30 seconds without showing a loading state", async () => {
    render(<TopScorersList />);
    await tick();
    expect(screen.getByText("41.4")).toBeInTheDocument();
    topScorers.mockResolvedValue({
      items: [{ ...gibbs, fantasy_points: 50.1 }, smithNjigba],
      week: 3,
    });

    await tick(POLL_INTERVAL_MS);

    expect(screen.getByText("50.1")).toBeInTheDocument();
    expect(screen.queryByText("Loading…")).not.toBeInTheDocument();
    expect(topScorers).toHaveBeenCalledTimes(2);
  });
});
