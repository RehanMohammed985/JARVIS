import type { Config } from "tailwindcss";

export default {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx}",
    "./types/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "var(--font-inter)",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        exo: ["var(--font-exo)", "ui-sans-serif", "system-ui", "sans-serif"],
        orbitron: ["var(--font-orbitron)", "ui-sans-serif", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        jarvis: {
          bg: "#030305",
        },
        holo: {
          cyan: "#5ef2ff",
          blue: "#3a7dff",
          magenta: "#c86bff",
          dim: "rgba(94, 242, 255, 0.12)",
        },
      },
      keyframes: {
        "jarvis-scan": {
          "0%, 100%": { transform: "translateX(-100%)" },
          "50%": { transform: "translateX(280%)" },
        },
        "bloom-pulse": {
          "0%, 100%": { opacity: "0.55", transform: "scale(0.96)" },
          "50%": { opacity: "1", transform: "scale(1.04)" },
        },
        "holo-flicker": {
          "0%, 100%": { opacity: "0.97" },
          "48%": { opacity: "1" },
          "50%": { opacity: "0.88" },
          "52%": { opacity: "1" },
        },
        "ambient-drift": {
          "0%, 100%": { transform: "translate(0, 0) scale(1)" },
          "33%": { transform: "translate(0.3%, -0.4%) scale(1.01)" },
          "66%": { transform: "translate(-0.25%, 0.35%) scale(0.99)" },
        },
      },
      animation: {
        "jarvis-scan": "jarvis-scan 1.1s ease-in-out infinite",
        "bloom-pulse": "bloom-pulse 4.2s ease-in-out infinite",
        "holo-flicker": "holo-flicker 5.5s ease-in-out infinite",
        "ambient-drift": "ambient-drift 16s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
