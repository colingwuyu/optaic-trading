/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["\"Space Grotesk\"", "ui-sans-serif", "system-ui"],
        display: ["\"Fraunces\"", "serif"],
      },
      colors: {
        ink: {
          900: "#0f172a",
          800: "#1e293b",
          700: "#334155",
        },
        fog: {
          50: "#f8fafc",
          100: "#f1f5f9",
          200: "#e2e8f0",
        },
        accent: {
          500: "#16a34a",
          600: "#15803d",
        },
      },
      boxShadow: {
        soft: "0 18px 60px rgba(15, 23, 42, 0.12)",
      },
    },
  },
  plugins: [],
};
