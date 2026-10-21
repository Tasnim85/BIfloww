import type { Config } from "tailwindcss";

// Colors come from CSS variables (src/app/globals.css): one palette, light and dark.
const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), surface: v("surface"), "surface-2": v("surface-2"), line: v("line"),
        ink: v("ink"), muted: v("muted"), subtle: v("subtle"),
        primary: { DEFAULT: v("primary"), fg: v("primary-fg"), soft: v("primary-soft") },
        accent: { DEFAULT: v("accent"), fg: v("accent-fg"), soft: v("accent-soft") },
        navy: v("navy"),
        ok: { DEFAULT: v("ok"), soft: v("ok-soft") },
        warn: { DEFAULT: v("warn"), soft: v("warn-soft") },
        bad: { DEFAULT: v("bad"), soft: v("bad-soft") },
      },
      fontFamily: {
        display: ["Poppins", "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: { xl: "14px", "2xl": "20px" },
      boxShadow: {
        card: "0 1px 2px rgb(15 42 61 / 0.04), 0 8px 24px -12px rgb(15 42 61 / 0.12)",
        lift: "0 2px 4px rgb(15 42 61 / 0.06), 0 24px 48px -20px rgb(15 42 61 / 0.25)",
      },
      keyframes: {
        flow: { "0%": { strokeDashoffset: "24" }, "100%": { strokeDashoffset: "0" } },
        pulseRing: { "0%": { transform: "scale(0.9)", opacity: "0.7" }, "100%": { transform: "scale(1.6)", opacity: "0" } },
      },
      animation: { flow: "flow 1s linear infinite", pulseRing: "pulseRing 1.6s ease-out infinite" },
    },
  },
  plugins: [],
} satisfies Config;
