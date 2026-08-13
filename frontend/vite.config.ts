import react from '@vitejs/plugin-react'
// `defineConfig` is imported from 'vitest/config' rather than 'vite' because this
// config declares a `test` key: plain vite's `defineConfig` type has no knowledge of
// vitest's config shape and type-checking fails otherwise.
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL ?? 'http://backend:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
  },
})
