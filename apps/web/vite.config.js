import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
    plugins: [react()],
    server: { proxy: { '/api': { target: `http://127.0.0.1:${process.env.E2E_API_PORT || process.env.API_PORT || '8000'}`, changeOrigin: true } } },
    test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', globals: true },
});
