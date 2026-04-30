import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--bg-canvas)",
        surface: "var(--bg-surface)",
        elevated: "var(--bg-elevated)",
        overlay: "var(--bg-overlay)",
        rail: "var(--bg-rail)",
        ink: {
          DEFAULT: "var(--text-primary)",
          muted: "#2f3a4d",
        },
        argus: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          tertiary: "var(--text-tertiary)",
          quaternary: "var(--text-quaternary)",
          inverse: "var(--text-inverse)",
          accent: "var(--text-accent)",
          oxblood: "var(--text-oxblood)",
          gold: "var(--text-gold)",
          border: {
            subtle: "var(--border-subtle)",
            moderate: "var(--border-moderate)",
            strong: "var(--border-strong)",
            accent: "var(--border-accent)",
          },
          // Trust palette (citation badges, confidence pills)
          firm: "var(--trust-firm)",
          "firm-bg": "var(--trust-firm-bg)",
          "firm-border": "var(--trust-firm-border)",
          credible: "var(--trust-credible)",
          "credible-bg": "var(--trust-credible-bg)",
          "credible-border": "var(--trust-credible-border)",
          web: "var(--trust-web)",
          "web-bg": "var(--trust-web-bg)",
          "web-border": "var(--trust-web-border)",
          contested: "var(--trust-contested)",
          "contested-bg": "var(--trust-contested-bg)",
          "contested-border": "var(--trust-contested-border)",
          // Legacy semantic aliases
          success: "var(--semantic-success)",
          "success-subtle": "var(--semantic-success-subtle)",
          "success-border": "var(--semantic-success-border)",
          warning: "var(--semantic-warning)",
          "warning-subtle": "var(--semantic-warning-subtle)",
          "warning-border": "var(--semantic-warning-border)",
          danger: "var(--semantic-danger)",
          "danger-subtle": "var(--semantic-danger-subtle)",
          "danger-border": "var(--semantic-danger-border)",
          neutral: "var(--semantic-neutral)",
          "neutral-subtle": "var(--semantic-neutral-subtle)",
          "info-subtle": "var(--semantic-info-subtle)",
          "info-border": "var(--semantic-info-border)",
        },
      },
      borderRadius: {
        argus: "var(--radius-btn)",
        "argus-sm": "var(--radius-sm)",
        "argus-md": "var(--radius-md)",
        "argus-lg": "var(--radius-lg)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        serif: ["var(--font-source-serif)", "Georgia", "serif"],
        mono: ['var(--font-jetbrains-mono)', "ui-monospace", "monospace"],
      },
      boxShadow: {
        argus: "var(--shadow-md)",
        "argus-sm": "var(--shadow-sm)",
        "argus-lg": "var(--shadow-lg)",
        "argus-xl": "var(--shadow-xl)",
        recommendation: "var(--shadow-recommendation)",
        popover: "var(--shadow-popover)",
      },
      keyframes: {
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        shimmer: "shimmer 1.4s infinite linear",
      },
    },
  },
  plugins: [],
};
export default config;
