import "@testing-library/jest-dom";

// jsdom doesn't implement ResizeObserver; Recharts' ResponsiveContainer needs it.
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

global.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;

// jsdom doesn't implement scrolling; components that scroll on navigation just need it to exist.
window.scrollTo = jest.fn() as unknown as typeof window.scrollTo;
Element.prototype.scrollIntoView = jest.fn();
