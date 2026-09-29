import { act, renderHook } from "@testing-library/react";
import { usePolling } from "./usePolling";

const tick = (ms: number) => act(async () => jest.advanceTimersByTime(ms));

let hidden = false;
Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });

beforeEach(() => {
  jest.useFakeTimers();
  hidden = false;
});

afterEach(() => jest.useRealTimers());

describe("usePolling", () => {
  it("does not call the function on mount", () => {
    const fn = jest.fn();
    renderHook(() => usePolling(fn, 1000));

    expect(fn).not.toHaveBeenCalled();
  });

  it("calls the function once per interval", async () => {
    const fn = jest.fn();
    renderHook(() => usePolling(fn, 1000));

    await tick(1000);
    expect(fn).toHaveBeenCalledTimes(1);
    await tick(1000);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("always uses the latest callback without resetting the interval", async () => {
    const first = jest.fn();
    const second = jest.fn();
    const { rerender } = renderHook(({ fn }) => usePolling(fn, 1000), {
      initialProps: { fn: first },
    });
    rerender({ fn: second });

    await tick(1000);

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("skips a tick while the tab is hidden", async () => {
    const fn = jest.fn();
    renderHook(() => usePolling(fn, 1000));
    hidden = true;

    await tick(1000);

    expect(fn).not.toHaveBeenCalled();
  });

  it("catches up as soon as the tab is shown again", async () => {
    const fn = jest.fn();
    renderHook(() => usePolling(fn, 1000));
    hidden = true;
    await tick(1000);
    expect(fn).not.toHaveBeenCalled();

    hidden = false;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("stops polling once unmounted", async () => {
    const fn = jest.fn();
    const { unmount } = renderHook(() => usePolling(fn, 1000));
    unmount();

    await tick(5000);

    expect(fn).not.toHaveBeenCalled();
  });
});
