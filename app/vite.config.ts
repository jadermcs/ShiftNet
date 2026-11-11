import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// The app reads and writes through the local ShiftNet API (backend/: `uv run shiftnet serve`).
// SHIFTNET_API (environment or .env) overrides where /api is proxied to.
export default defineConfig(({ mode }) => {
  const api = loadEnv(mode, '.', 'SHIFTNET_').SHIFTNET_API || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: { proxy: { '/api': api } },
    preview: { proxy: { '/api': api } },
  };
});
