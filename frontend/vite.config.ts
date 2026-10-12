import { defineConfig } from 'vite';
import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  root: '.',
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: resolve(import.meta.dirname, 'index.html'),
        'floating-composer': resolve(import.meta.dirname, 'floating-composer.html'),
      },
    },
  },
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
});
