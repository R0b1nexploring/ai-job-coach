/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#14201a',
        sage: '#2f6b56',
        cream: '#f3eee4',
        coral: '#d96a4a',
        paper: '#fffdf8',
      },
      boxShadow: {
        lift: '0 1px 2px rgba(23,33,27,0.04), 0 18px 40px -24px rgba(23,33,27,0.28)',
      },
    },
  },
  plugins: [],
}

