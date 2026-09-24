import { fireEvent, render, screen } from "@testing-library/react";
import AveragesTable from "./AveragesTable";
import ConsistencyStrip from "./ConsistencyStrip";
import PlayerAvatar from "./PlayerAvatar";
import StatusPill from "./StatusPill";
import TeamLogo from "./TeamLogo";
import { makeEntry, makeNbaGames, makeTeam } from "@/test/fixtures";

describe("StatusPill", () => {
  it("shows Active or Inactive when there is no injury designation", () => {
    const { rerender } = render(<StatusPill injuryStatus={null} active />);
    expect(screen.getByText("Active")).toHaveClass("text-good");

    rerender(<StatusPill injuryStatus={null} active={false} />);
    expect(screen.getByText("Inactive")).toHaveClass("text-bad");
  });

  it.each([
    ["Questionable", "text-warn"],
    ["Doubtful", "text-warn"],
    ["Day-To-Day", "text-warn"],
    ["Out", "text-bad"],
    ["Injured Reserve", "text-bad"],
  ])("shows %s in its severity color, ahead of roster status", (status, tone) => {
    render(<StatusPill injuryStatus={status} active />);

    expect(screen.getByText(status)).toHaveClass(tone);
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });
});

describe("PlayerAvatar", () => {
  it("shows the headshot when there is one", () => {
    const { container } = render(
      <PlayerAvatar headshotUrl="https://img.example/1.png" teamColor="#123456" />,
    );

    expect(container.querySelector("img")).toHaveAttribute("src", "https://img.example/1.png");
  });

  it("shows a silhouette when there is no headshot", () => {
    const { container } = render(<PlayerAvatar headshotUrl={null} teamColor={null} />);

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("falls back to the silhouette when the image fails to load", () => {
    const { container } = render(
      <PlayerAvatar headshotUrl="https://img.example/broken.png" teamColor={null} />,
    );

    fireEvent.error(container.querySelector("img")!);

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});

describe("TeamLogo", () => {
  it("shows the logo image", () => {
    const { container } = render(<TeamLogo team={makeTeam({ logo_url: "https://img.example/t.png" })} />);

    expect(container.querySelector("img")).toHaveAttribute("src", "https://img.example/t.png");
  });

  it("falls back to the abbreviation on the team's color", () => {
    render(<TeamLogo team={makeTeam({ logo_url: null, abbreviation: "GSW" })} />);

    expect(screen.getByText("GSW")).toBeInTheDocument();
  });
});

describe("AveragesTable", () => {
  it("averages each stat over the last 5, last 10 and all games", () => {
    // Points newest-first: 32, 31, ... , 21 (12 games).
    render(
      <AveragesTable sport="NBA" entries={makeNbaGames(12)} rows={["points"]} selectedStat="points" />,
    );

    const row = screen.getByRole("row", { name: /^PTS/ });
    expect(row).toHaveTextContent("30"); // last 5: 28..32
    expect(row).toHaveTextContent("27.5"); // last 10: 23..32
    expect(row).toHaveTextContent("26.5"); // all 12: 21..32
  });

  it("uses full stat names for NFL rows, where abbreviations repeat", () => {
    const entries = [makeEntry({ stats: { rushing_yards: 50, receiving_yards: 20 } })];
    render(
      <AveragesTable
        sport="NFL"
        entries={entries}
        rows={["rushing_yards", "receiving_yards"]}
        selectedStat="rushing_yards"
      />,
    );

    expect(screen.getByText("Rushing yards")).toBeInTheDocument();
    expect(screen.getByText("Receiving yards")).toBeInTheDocument();
  });
});

describe("ConsistencyStrip", () => {
  it("summarizes the floor, median, average and ceiling of the selected stat", () => {
    const entries = [10, 20, 30, 40, 50].map((points, index) =>
      makeEntry({ game_id: index, stats: { points } }),
    );
    render(<ConsistencyStrip sport="NBA" entries={entries} stat="points" />);

    expect(screen.getByText("Floor").previousSibling).toHaveTextContent("10");
    expect(screen.getByText("Median").previousSibling).toHaveTextContent("30");
    expect(screen.getByText("Ceiling").previousSibling).toHaveTextContent("50");
    expect(
      screen.getByRole("img", { name: /Spread of Points across 5 games from 10 to 50, median 30/ }),
    ).toBeInTheDocument();
  });

  it("shows the average, which can differ from the median", () => {
    const entries = [0, 0, 30, 30, 90].map((points, index) =>
      makeEntry({ game_id: index, stats: { points } }),
    );
    render(<ConsistencyStrip sport="NBA" entries={entries} stat="points" />);

    expect(screen.getByText("Median").previousSibling).toHaveTextContent("30");
    expect(screen.getByText("Average").previousSibling).toHaveTextContent("30");

    const skewed = [0, 0, 10, 10, 80].map((points, index) =>
      makeEntry({ game_id: index, stats: { points } }),
    );
    render(<ConsistencyStrip sport="NBA" entries={skewed} stat="points" />);

    expect(screen.getAllByText("Average")[1].previousSibling).toHaveTextContent("20");
    expect(screen.getAllByText("Median")[1].previousSibling).toHaveTextContent("10");
  });

  it("names the average in the plot's description for screen readers", () => {
    const entries = [10, 20, 30].map((points, index) => makeEntry({ game_id: index, stats: { points } }));
    render(<ConsistencyStrip sport="NBA" entries={entries} stat="points" />);

    expect(screen.getByRole("img", { name: /average 20/ })).toBeInTheDocument();
  });

  it("draws one dot per game, even when every game is identical", () => {
    const entries = [1, 2, 3].map((id) => makeEntry({ game_id: id, stats: { points: 12 } }));
    const { container } = render(<ConsistencyStrip sport="NBA" entries={entries} stat="points" />);

    expect(container.querySelectorAll("circle")).toHaveLength(3);
  });

  it("averages the two middle games for an even number of games", () => {
    const entries = [10, 20].map((points, index) => makeEntry({ game_id: index, stats: { points } }));
    render(<ConsistencyStrip sport="NBA" entries={entries} stat="points" />);

    expect(screen.getByText("Median").previousSibling).toHaveTextContent("15");
  });
});
