import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const proxyTarget = process.env.ADMIN_API_PROXY ?? 'http://127.0.0.1:58084';
const proxy = {
  '/api': { target: proxyTarget, changeOrigin: false },
  '/health': { target: proxyTarget, changeOrigin: false },
  '/ready': { target: proxyTarget, changeOrigin: false },
};

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
});
