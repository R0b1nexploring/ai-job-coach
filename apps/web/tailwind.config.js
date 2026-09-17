/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#f5f6f3',
        surface: '#ffffff',
        ink: '#18211d',
        'ink-secondary': '#5f6963',
        'ink-muted': '#8a938d',
        line: '#e2e5df',
        'line-strong': '#cfd4cc',
        accent: '#c76345',
        interactive: '#2d6a4f',
        // Legacy aliases kept so existing markup keeps resolving.
        sage: '#2d6a4f',
        cream: '#f5f6f3',
        coral: '#c76345',
        paper: '#ffffff',
      },
      fontFamily: {
        display: ['Newsreader', 'Noto Serif SC', 'Songti SC', 'Georgia', 'serif'],
        sans: ['Inter', 'PingFang SC', 'Noto Sans SC', 'system-ui', '-apple-system', 'sans-serif'],
      },
      // Radius is capped at 0 / 2 / 4 / 6. Larger utility names intentionally
      // collapse onto 6px so old markup cannot reintroduce big rounded corners.
      borderRadius: {
        none: '0px',
        sm: '2px',
        DEFAULT: '4px',
        md: '6px',
        lg: '6px',
        xl: '6px',
        '2xl': '6px',
        '3xl': '6px',
        full: '9999px',
      },
      // Elevation is reserved for overlays (menus, drawers) only.
      boxShadow: {
        sm: 'none',
        DEFAULT: 'none',
        md: 'none',
        lg: 'none',
        lift: 'none',
        xl: '0 8px 24px -16px rgba(24, 33, 29, 0.28)',
        '2xl': '0 8px 24px -16px rgba(24, 33, 29, 0.28)',
      },
    },
  },
  plugins: [],
}
