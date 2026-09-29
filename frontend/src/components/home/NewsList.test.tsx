import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NewsList from "./NewsList";
import { getHeadlines } from "@/lib/api";
import { POLL_INTERVAL_MS } from "@/lib/usePolling";
import { makeTeam } from "@/test/fixtures";
import type { HeadlineEntry } from "@/lib/api";

jest.mock("@/lib/api", () => ({ getHeadlines: jest.fn() }));

const headlines = jest.mocked(getHeadlines);

function makeHeadline(overrides: Partial<HeadlineEntry> = {}): HeadlineEntry {
  return {
    kind: "performance",
    player_id: 1,
    player_name: "Brock Purdy",
    sport: "NFL",
    team: makeTeam({ id: 1, name: "49ers", abbreviation: "SF" }),
    position: "QB",
    headshot_url: null,
    headline: "Brock Purdy threw for 297 yards and 4 TDs in a win vs Cardinals.",
    at: "2026-09-27T20:05:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  headlines.mockReset();
});

describe("NewsList", () => {
  it("shows a performance headline with its label and player line", async () => {
    headlines.mockResolvedValue({ items: [makeHeadline()] });
    render(<NewsList />);

    expect(await screen.findByText(/Brock Purdy threw for 297 yards/)).toBeInTheDocument();
    expect(screen.getByText("Performance")).toBeInTheDocument();
    expect(screen.getByText(/Brock Purdy · QB · SF/)).toBeInTheDocument();
  });

  it("shows an injury headline with its label", async () => {
    headlines.mockResolvedValue({
      items: [
        makeHeadline({
          kind: "injury",
          player_id: 2,
          player_name: "De'Von Achane",
          position: "RB",
          headline: "The Dolphins placed Achane (knee) on injured reserve Monday.",
        }),
      ],
    });
    render(<NewsList />);

    expect(await screen.findByText(/placed Achane \(knee\) on injured reserve/)).toBeInTheDocument();
    expect(screen.getByText("Injury")).toBeInTheDocument();
  });

  it("links to the player's page", async () => {
    headlines.mockResolvedValue({ items: [makeHeadline()] });
    render(<NewsList />);

    expect(await screen.findByRole("link", { name: /Brock Purdy/ })).toHaveAttribute(
      "href",
      "/players/1",
    );
  });

  it("switches sports and refetches", async () => {
    headlines.mockResolvedValue({ items: [] });
    const user = userEvent.setup();
    render(<NewsList />);
    await screen.findByText("No fantasy news right now.");

    await user.click(screen.getByRole("button", { name: "NBA" }));

    await waitFor(() => expect(headlines).toHaveBeenLastCalledWith("NBA", 12));
  });

  it("silently refetches every 30 seconds so a new report shows up on its own", async () => {
    jest.useFakeTimers();
    try {
      headlines.mockResolvedValue({ items: [makeHeadline()] });
      render(<NewsList />);
      await act(async () => jest.advanceTimersByTime(0));
      expect(screen.getByText(/Brock Purdy threw for 297 yards/)).toBeInTheDocument();

      headlines.mockResolvedValue({
        items: [makeHeadline({ headline: "Brock Purdy threw for 350 yards and 5 TDs in a win." })],
      });
      await act(async () => jest.advanceTimersByTime(POLL_INTERVAL_MS));

      expect(screen.getByText(/350 yards and 5 TDs/)).toBeInTheDocument();
      expect(headlines).toHaveBeenCalledTimes(2);
    } finally {
      jest.useRealTimers();
    }
  });
});
