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
        // Development affordance, not frontend authentication: one shared token,
        // injected here by the dev proxy so it never enters browser JavaScript. No
        // login, no per-user identity, no logout. A real login flow replaces this
        // when multi-user lands.
        headers: process.env.API_TOKEN
          ? { Authorization: `Bearer ${process.env.API_TOKEN}` }
          : {},
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
  },
})
