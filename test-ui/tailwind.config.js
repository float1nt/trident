/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        notion: {
          bg: "var(--notion-bg)",
          surface: "var(--notion-surface)",
          "surface-alt": "var(--notion-surface-alt)",
          "surface-hover": "var(--notion-surface-hover)",
          border: "var(--notion-border)",
          "border-strong": "var(--notion-border-strong)",
          text: "var(--notion-text-primary)",
          secondary: "var(--notion-text-secondary)",
          tertiary: "var(--notion-text-tertiary)",
          accent: "var(--notion-accent)",
          "accent-text": "var(--notion-accent-text)",
          "accent-bg": "var(--notion-accent-bg)",
          success: "var(--notion-green)",
          "success-bg": "var(--notion-green-bg)",
          danger: "var(--notion-red)",
          "danger-bg": "var(--notion-red-bg)",
          warning: "var(--notion-yellow)",
          "warning-bg": "var(--notion-yellow-bg)",
          info: "var(--notion-blue)",
          "info-bg": "var(--notion-blue-bg)",
          orange: "var(--notion-orange)",
        },
      },
    },
  },
  plugins: [],
  corePlugins: {
    preflight: false,
  },
};
