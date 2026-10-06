import { defineConfig } from 'astro/config';

// Static build: the Python backend mounts web/dist via StaticFiles
// and fetches JSON from /api/*. In dev, Astro runs on :4321 and talks
// to the backend on :8080 with CORS enabled.
export default defineConfig({
  output: 'static',
  build: {
    assets: 'assets-build',
  },
  server: {
    port: 4321,
    host: '127.0.0.1',
  },
  vite: {
    server: {
      proxy: {
        // Forward API and SSE calls to the Python backend during dev,
        // so same-origin assumptions hold.
        '/api': {
          target: 'http://localhost:8080',
          changeOrigin: true,
        },
        '/healthz': { target: 'http://localhost:8080' },
        '/readyz': { target: 'http://localhost:8080' },
      },
    },
  },
});
