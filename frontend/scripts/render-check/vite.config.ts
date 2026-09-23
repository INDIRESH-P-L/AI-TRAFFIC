import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Bundles the render check for Node. The frontend has no test runner, and this
 * deliberately does not add one: `react-dom/server` is already a dependency,
 * so a real render can be verified with nothing new installed.
 */
const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1'));

export default defineConfig({
  root: path.resolve(here, '../..'),
  plugins: [react()],
  logLevel: 'warn',
  build: {
    ssr: path.resolve(here, 'entry.tsx'),
    outDir: path.resolve(here, 'out'),
    emptyOutDir: true,
    minify: false,
    rollupOptions: { output: { entryFileNames: 'check.js' } },
  },
});
