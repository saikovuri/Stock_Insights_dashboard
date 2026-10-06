import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Preview serves the production headers so browser tests enforce the deployed CSP.
const vercel = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8'));
const productionHeaders = Object.fromEntries(vercel.headers[0].headers.map(({ key, value }) => [key, value]));

export default defineConfig({
  plugins: [react()],
  preview: { headers: productionHeaders },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ['recharts'],
          candles: ['lightweight-charts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
