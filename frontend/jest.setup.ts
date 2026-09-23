import "@testing-library/jest-dom";

// jsdom doesn't implement ResizeObserver; Recharts' ResponsiveContainer needs it.
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

global.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;
