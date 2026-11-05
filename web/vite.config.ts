import { defineConfig } from 'vite';

export default defineConfig({
  build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false },
  server: {
    proxy: {
      '/v1': 'http://127.0.0.1:8001',
      '/auth': 'http://127.0.0.1:8001',
      '/health': 'http://127.0.0.1:8001',
    },
  },
});
