import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StartSitBox from "./StartSitBox";
import { listDefenses, listPlayers } from "@/lib/api";
import { makePlayerListItem } from "@/test/fixtures";

const push = jest.fn();
jest.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
jest.mock("@/lib/api", () => ({
  listPlayers: jest.fn(),
  listDefenses: jest.fn(),
}));

const players = jest.mocked(listPlayers);
const defenses = jest.mocked(listDefenses);

async function addPlayer(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.type(screen.getByRole("combobox", { name: "Add a player" }), name);
  await user.click(await screen.findByRole("option", { name: new RegExp(name, "i") }));
}

beforeEach(() => {
  push.mockReset();
  players.mockReset();
  defenses.mockReset();
  defenses.mockResolvedValue({ items: [], total: 0, limit: 3, offset: 0 });
});

describe("StartSitBox", () => {
  it("searches and adds players, then sends View advice to the /start page with their picks", async () => {
    players.mockResolvedValue({
      items: [makePlayerListItem({ id: 1, name: "Jahmyr Gibbs", position: "RB", sport: "NFL" })],
      total: 1,
      limit: 8,
      offset: 0,
    });
    const user = userEvent.setup();
    render(<StartSitBox />);

    await addPlayer(user, "Gibbs");
    expect(screen.getByText("Jahmyr Gibbs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View advice" })).toBeDisabled();

    players.mockResolvedValue({
      items: [makePlayerListItem({ id: 2, name: "CeeDee Lamb", position: "WR", sport: "NFL" })],
      total: 1,
      limit: 8,
      offset: 0,
    });
    await addPlayer(user, "Lamb");

    const advise = screen.getByRole("button", { name: "View advice" });
    expect(advise).toBeEnabled();
    await user.click(advise);

    expect(push).toHaveBeenCalledWith("/start?picks=p1,p2&advice=1");
  });

  it("removes a picked player with its chip's remove button", async () => {
    players.mockResolvedValue({
      items: [makePlayerListItem({ id: 1, name: "Jahmyr Gibbs", sport: "NFL" })],
      total: 1,
      limit: 8,
      offset: 0,
    });
    const user = userEvent.setup();
    render(<StartSitBox />);
    await addPlayer(user, "Gibbs");

    await user.click(screen.getByRole("button", { name: "Remove Jahmyr Gibbs" }));

    expect(screen.queryByText("Jahmyr Gibbs")).not.toBeInTheDocument();
  });

  it("stops adding players once five are picked", async () => {
    players.mockResolvedValue({
      items: Array.from({ length: 6 }, (_, i) =>
        makePlayerListItem({ id: i + 1, name: `Player ${i + 1}`, sport: "NFL" }),
      ),
      total: 6,
      limit: 8,
      offset: 0,
    });
    const user = userEvent.setup();
    render(<StartSitBox />);

    for (let i = 1; i <= 5; i++) {
      await addPlayer(user, `Player ${i}`);
    }

    expect(screen.getByPlaceholderText("Remove a player to add another")).toBeDisabled();
  });

  it("switching sport clears the picks and switches the search to that sport", async () => {
    players.mockResolvedValue({
      items: [makePlayerListItem({ id: 1, name: "Jahmyr Gibbs", sport: "NFL" })],
      total: 1,
      limit: 8,
      offset: 0,
    });
    const user = userEvent.setup();
    render(<StartSitBox />);
    await addPlayer(user, "Gibbs");
    expect(screen.getByText("Jahmyr Gibbs")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "NBA" }));

    expect(screen.queryByText("Jahmyr Gibbs")).not.toBeInTheDocument();
    await user.type(screen.getByRole("combobox", { name: "Add a player" }), "cur");
    await waitFor(() =>
      expect(players).toHaveBeenLastCalledWith(expect.objectContaining({ sport: "NBA" })),
    );
  });
});
