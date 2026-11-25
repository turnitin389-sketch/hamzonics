import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "Segoe UI", "Arial", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["Georgia", "Times New Roman", "serif"],
      },
      colors: {
        // Turnitin Report: dark teal + bright cyan from the logo.
        brand: {
          50: "#edfffe",
          100: "#d5fbf8",
          200: "#abf7f1",
          500: "#0097ff",
          600: "#007acc",
          700: "#005f99",
          900: "#013b46",
        },
        ink: { 900: "#012a32", 800: "#013b46", 700: "#025264" },
        accent: { 400: "#33b5ff", 500: "#0097ff", 600: "#0080db" },
      },
      boxShadow: {
        soft: "0 1px 2px rgba(16,24,40,.04), 0 8px 24px -6px rgba(16,24,40,.10)",
        glow: "0 0 0 1px rgba(0,151,255,.15), 0 12px 40px -8px rgba(0,151,255,.35)",
      },
      keyframes: {
        scan: { "0%": { top: "-10%" }, "100%": { top: "105%" } },
        shimmer: { "0%": { backgroundPosition: "-400px 0" }, "100%": { backgroundPosition: "400px 0" } },
        fadeUp: { "0%": { opacity: "0", transform: "translateY(8px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
        floaty: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-6px)" } },
        gradient: { "0%,100%": { backgroundPosition: "0% 50%" }, "50%": { backgroundPosition: "100% 50%" } },
        ticker: { "0%": { transform: "translateY(0)" }, "100%": { transform: "translateY(-50%)" } },
        ping2: { "0%": { transform: "scale(1)", opacity: ".6" }, "100%": { transform: "scale(2.2)", opacity: "0" } },
      },
      animation: {
        scan: "scan 2.6s cubic-bezier(.45,0,.55,1) infinite",
        shimmer: "shimmer 1.6s linear infinite",
        fadeUp: "fadeUp .5s ease-out both",
        floaty: "floaty 4s ease-in-out infinite",
        gradient: "gradient 8s ease infinite",
        ticker: "ticker 40s linear infinite",
        ping2: "ping2 1.6s cubic-bezier(0,0,.2,1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
