import { defineConfig } from 'vite';
import { resolve } from 'node:path';
import { readFileSync } from 'node:fs';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version) },
  plugins: [react(), tailwindcss()],
  root: '.',
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: resolve(import.meta.dirname, 'index.html'),
        'voice-hud': resolve(import.meta.dirname, 'voice-hud.html'),
        'floating-composer': resolve(import.meta.dirname, 'floating-composer.html'),
        dashboard: resolve(import.meta.dirname, 'dashboard.html'),
      },
    },
  },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
});
