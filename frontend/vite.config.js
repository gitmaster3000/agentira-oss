import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend proxy target:
// - host dev (npm run dev on your laptop): localhost:8111 by default
// - docker dev (vite inside the dev container): VITE_PROXY_TARGET set
//   to http://backend:8111 so the proxy reaches the sibling service.
// Same vite.config.js works in both modes.
const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://localhost:8111';

export default defineConfig({
    plugins: [react()],
    server: {
        port: 3111,
        host: true,  // listen on 0.0.0.0 so docker port-mapping works
        proxy: {
            '/api': {
                target: proxyTarget,
                changeOrigin: true,
                ws: true,  // proxy /api/forge/daemon/ws + similar
            },
        },
    },
});
