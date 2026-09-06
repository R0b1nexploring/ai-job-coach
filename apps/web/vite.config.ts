import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const apiPort = process.env.E2E_API_PORT || process.env.API_PORT || '8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true } },
  },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', globals: true, include: ['src/**/*.test.{ts,tsx}'] },
})
