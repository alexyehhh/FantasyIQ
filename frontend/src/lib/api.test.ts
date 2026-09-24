import {
  getDefense,
  getDefenseSchedule,
  getDefenseSeason,
  getDefenseStats,
  getPlayer,
  getPlayerSchedule,
  getPlayerSeason,
  getPlayerStats,
  getScoringPreset,
  listDefenses,
  listPlayers,
} from "./api";

describe("player API client", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  it("listPlayers builds the query string from given params and returns the parsed body", async () => {
    const body = { items: [], total: 0, limit: 50, offset: 0 };
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => body,
    });

    const result = await listPlayers({ sport: "NBA", search: "curry", limit: 10 });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/players?"),
      expect.objectContaining({ cache: "no-store" }),
    );
    const [url] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain("sport=NBA");
    expect(url).toContain("search=curry");
    expect(url).toContain("limit=10");
    expect(result).toEqual(body);
  });

  it("listPlayers throws when the backend responds with an error status", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 500 });

    await expect(listPlayers()).rejects.toThrow("Failed to list players: 500");
  });

  it("getPlayer returns null on a 404 instead of throwing", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 404 });

    await expect(getPlayer(999)).resolves.toBeNull();
  });

  it("getPlayer returns the parsed player on success", async () => {
    const player = { id: 1, name: "Test Player", sport: "NBA" };
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => player,
    });

    await expect(getPlayer(1)).resolves.toEqual(player);
  });

  it("getPlayerStats returns null on a 404", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 404 });

    await expect(getPlayerStats(999)).resolves.toBeNull();
  });

  it("getPlayerStats appends the limit query param when given", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => [],
    });

    await getPlayerStats(1, 20);

    const [url] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain("/api/v1/players/1/stats?limit=20");
  });

  it("listPlayers repeats the position param once per position", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
    });

    await listPlayers({ sport: "NFL", positions: ["RB", "WR", "TE"] });

    const [url] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain("sport=NFL");
    expect(url).toContain("position=RB&position=WR&position=TE");
  });

  it("listPlayers passes the sort and offset through", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 50, offset: 100 }),
    });

    await listPlayers({ sport: "NBA", sort: "fantasy_points", limit: 50, offset: 100 });

    const [url] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain("sort=fantasy_points");
    expect(url).toContain("offset=100");
    expect(url).toContain("limit=50");
  });

  it("getPlayerSchedule returns null on a 404", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 404 });

    await expect(getPlayerSchedule(999)).resolves.toBeNull();
  });

  it("getPlayerSchedule fetches the player's schedule", async () => {
    const schedule = [{ game_id: 1 }];
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => schedule });

    await expect(getPlayerSchedule(7)).resolves.toEqual(schedule);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain("/api/v1/players/7/schedule");
  });

  it("getPlayerSchedule throws on other errors", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 500 });

    await expect(getPlayerSchedule(7)).rejects.toThrow("Failed to fetch schedule for player 7: 500");
  });
});

describe("defense API client", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  it("listDefenses builds the query string and returns the parsed body", async () => {
    const body = { items: [], total: 0, limit: 50, offset: 50 };
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => body });

    const result = await listDefenses({ search: "bears", sort: "fantasy_points", limit: 50, offset: 50 });

    const [url, options] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain("/api/v1/defenses?");
    expect(url).toContain("search=bears");
    expect(url).toContain("sort=fantasy_points");
    expect(url).toContain("offset=50");
    expect(options).toEqual(expect.objectContaining({ cache: "no-store" }));
    expect(result).toEqual(body);
  });

  it("listDefenses throws when the backend responds with an error status", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 500 });

    await expect(listDefenses()).rejects.toThrow("Failed to list defenses: 500");
  });

  it.each([
    ["getDefense", () => getDefense(7)],
    ["getDefenseStats", () => getDefenseStats(7)],
    ["getDefenseSchedule", () => getDefenseSchedule(7)],
  ])("%s returns null on a 404 and throws on other errors", async (_name, call) => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 404 });
    await expect(call()).resolves.toBeNull();

    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 500 });
    await expect(call()).rejects.toThrow("500");
  });

  it("getDefenseStats passes the limit and reads /defenses/{id}/stats", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => [] });

    await getDefenseStats(7, 200);

    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain("/api/v1/defenses/7/stats?limit=200");
  });
});

describe("getScoringPreset", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  it("returns the sport's default scoring config", async () => {
    const config = { name: "FantasyIQ standard", sport: "NBA" };
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => config });

    await expect(getScoringPreset("NBA")).resolves.toEqual(config);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain("/api/v1/scoring/presets/NBA");
  });

  it("returns null instead of throwing when the scoring can't be fetched", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 500 });
    await expect(getScoringPreset("NFL")).resolves.toBeNull();

    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error("network down"));
    await expect(getScoringPreset("NFL")).resolves.toBeNull();
  });
});

describe("season summary API calls", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  it.each([
    ["getPlayerSeason", getPlayerSeason, "/api/v1/players/5/season"],
    ["getDefenseSeason", getDefenseSeason, "/api/v1/defenses/5/season"],
  ])("%s reads the summary from the season endpoint", async (_name, call, path) => {
    const body = { season: "2026", games: 2, position_group: "QB", pool_size: 32, stats: {} };
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => body });

    await expect(call(5)).resolves.toEqual(body);
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain(path);
  });

  it.each([
    ["getPlayerSeason", getPlayerSeason],
    ["getDefenseSeason", getDefenseSeason],
  ])("%s returns null instead of throwing when it can't get a summary", async (_name, call) => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 404 });
    await expect(call(5)).resolves.toBeNull();

    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error("network down"));
    await expect(call(5)).resolves.toBeNull();

    // A player who hasn't played gets a 200 with a null body.
    (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => null });
    await expect(call(5)).resolves.toBeNull();
  });
});
