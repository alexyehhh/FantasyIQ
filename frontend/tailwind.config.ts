import type { Config } from "tailwindcss";

// Colors are CSS variables (defined in globals.css) so light and dark themes
// are one set of tokens instead of a `dark:` variant on every element.
const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        "ink-3": "var(--ink-3)",
        line: "var(--line)",
        "line-2": "var(--line-2)",
        accent: "var(--accent)",
        "on-accent": "var(--on-accent)",
        "accent-soft": "var(--accent-soft)",
        "bar-dim": "var(--bar-dim)",
        good: "var(--good)",
        "good-soft": "var(--good-soft)",
        bad: "var(--bad)",
        "bad-soft": "var(--bad-soft)",
        warn: "var(--warn)",
        "warn-soft": "var(--warn-soft)",
        nav: "var(--nav)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ["var(--font-display)", "Arial Narrow", "Arial", "sans-serif"],
      },
      boxShadow: {
        panel: "var(--shadow)",
      },
    },
  },
  plugins: [],
};

export default config;
