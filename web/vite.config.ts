// vitest/config re-exports defineConfig with the `test` block typed
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    // keeps the python side's /assets mount predictable
    assetsDir: 'assets',
  },
  server: {
    // `npm run dev` against a locally running api
    proxy: {
      '/api': 'http://localhost:7373',
      '/healthz': 'http://localhost:7373',
      '/sondaro.ics': 'http://localhost:7373',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    css: false,
  },
})
