import { act, render, screen } from "@testing-library/react";
import LiveRefresh, { REFRESH_INTERVAL_MS } from "./LiveRefresh";
import { getHealth } from "@/lib/api";

const router = { refresh: jest.fn() };
jest.mock("next/navigation", () => ({ useRouter: () => router }));
jest.mock("@/lib/api", () => ({ getHealth: jest.fn() }));

const mockedGetHealth = getHealth as jest.MockedFunction<typeof getHealth>;

let hidden = false;
Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });

/** Let the clock run `ms` and the promises it starts settle. */
const tick = (ms: number) =>
  act(async () => {
    jest.advanceTimersByTime(ms);
  });

describe("LiveRefresh", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    hidden = false;
    router.refresh.mockReset();
    mockedGetHealth.mockReset();
    mockedGetHealth.mockResolvedValue({ status: "ok", environment: "test" });
  });
  afterEach(() => jest.useRealTimers());

  it("tells the viewer the page updates by itself", () => {
    render(<LiveRefresh />);

    expect(screen.getByRole("status")).toHaveTextContent("Live · updates automatically");
  });

  it("refreshes the page in place every interval, not before", async () => {
    render(<LiveRefresh />);

    await tick(REFRESH_INTERVAL_MS - 1);
    expect(router.refresh).not.toHaveBeenCalled();
    await tick(1);
    expect(router.refresh).toHaveBeenCalledTimes(1);
    await tick(REFRESH_INTERVAL_MS);
    expect(router.refresh).toHaveBeenCalledTimes(2);
  });

  it("does not refresh while the tab is hidden, and catches up when it is shown", async () => {
    render(<LiveRefresh />);
    hidden = true;

    await tick(REFRESH_INTERVAL_MS * 3);
    expect(router.refresh).not.toHaveBeenCalled();

    hidden = false;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("leaves the page alone when the backend can't be reached, and tries again next time", async () => {
    mockedGetHealth.mockRejectedValueOnce(new Error("down"));
    render(<LiveRefresh />);

    await tick(REFRESH_INTERVAL_MS);
    expect(router.refresh).not.toHaveBeenCalled();

    await tick(REFRESH_INTERVAL_MS);
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("does not start a second refresh while one is still in flight", async () => {
    let finish: (value: { status: string; environment: string }) => void = () => {};
    mockedGetHealth.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    render(<LiveRefresh />);

    await tick(REFRESH_INTERVAL_MS * 3);
    expect(mockedGetHealth).toHaveBeenCalledTimes(1);

    await act(async () => finish({ status: "ok", environment: "test" }));
    await tick(REFRESH_INTERVAL_MS);
    expect(mockedGetHealth).toHaveBeenCalledTimes(2);
  });

  it("stops when the game is over and the page unmounts it", async () => {
    const { unmount } = render(<LiveRefresh />);
    unmount();

    await tick(REFRESH_INTERVAL_MS * 3);
    document.dispatchEvent(new Event("visibilitychange"));

    expect(router.refresh).not.toHaveBeenCalled();
    expect(mockedGetHealth).not.toHaveBeenCalled();
  });
});
