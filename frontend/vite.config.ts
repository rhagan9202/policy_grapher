import react from '@vitejs/plugin-react'
// `defineConfig` is imported from 'vitest/config' rather than 'vite' because this
// config declares a `test` key: plain vite's `defineConfig` type has no knowledge of
// vitest's config shape and type-checking fails otherwise.
import { defineConfig } from 'vitest/config'

const defaultAllowedHosts = [
  '5173--main--hopes-and-dreams--rhagan.coder.sand.uskgc.com',
]

const extraAllowedHosts = (process.env.VITE_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((host) => host.trim())
  .filter((host) => host.length > 0)

const allowedHosts = [...new Set([...defaultAllowedHosts, ...extraAllowedHosts])]

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts,
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL ?? 'http://backend:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        // Development affordance, not frontend authentication: one shared token,
        // injected here by the dev proxy so it never enters browser JavaScript. No
        // login, no per-user identity, no logout. A real login flow replaces this
        // when multi-user lands.
        //
        // All methods, by decision (ADR-018) — the review queue has to POST
        // verdicts, and a GET-only proxy cannot serve a UI that writes.
        //
        // The guard is the custom header, not the method. A cross-origin page
        // cannot set one: custom headers force a CORS preflight, and `mode:
        // 'no-cors'` — the only mode that lets a page fire a request it cannot
        // read — forbids them. So the drive-by `POST /api/reset` from any site
        // the developer happens to visit does not get a token injected.
        //
        // It stops a browser, not a local process. `curl -H 'x-policy-grapher-ui: 1'
        // -X POST localhost:5173/api/reset` still wipes the graph. The bound on that
        // is docker-compose publishing this port as 127.0.0.1:5173, so the caller is
        // already on the machine. Accepted and recorded in ADR-018.
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq, req) => {
            const fromUi = req.headers['x-policy-grapher-ui'] === '1'
            if (fromUi && process.env.API_TOKEN) {
              proxyReq.setHeader('authorization', `Bearer ${process.env.API_TOKEN}`)
            }
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
  },
})
