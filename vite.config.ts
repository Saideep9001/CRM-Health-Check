import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import type { ServerResponse } from 'node:http';
import { devApiPlugin } from './dev-server/devApi';

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string };

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000';
  // DEV_API=true serves the local development API (dev-server/devApi.ts) instead of proxying.
  const useDevApi = env.DEV_API === 'true';

  return {
    plugins: [react(), ...(useDevApi ? [devApiPlugin(env, process.cwd())] : [])],
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    define: { __APP_VERSION__: JSON.stringify(pkg.version) },
    server: {
      port: 5173,
      // Forward API calls to the FastAPI backend during development.
      proxy: useDevApi
        ? undefined
        : {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          configure: (proxy) => {
            // Report an unreachable backend as 503 so the client shows "service unavailable".
            proxy.on('error', (_err, _req, res) => {
              const r = res as ServerResponse;
              if (!r.headersSent) {
                r.writeHead(503, { 'Content-Type': 'application/json' });
                r.end(JSON.stringify({ detail: 'Backend unavailable' }));
              }
            });
          },
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            query: ['@tanstack/react-query'],
            charts: ['recharts'],
            motion: ['framer-motion'],
          },
        },
      },
    },
  };
});
