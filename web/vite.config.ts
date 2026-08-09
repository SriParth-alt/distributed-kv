import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In dev, proxy API + WebSocket to a locally running Helix node so the app is
// same-origin. In production the app is either served by the node itself or
// points at VITE_API_BASE.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/keys': 'http://127.0.0.1:8001',
      '/cluster': { target: 'http://127.0.0.1:8001', ws: true },
      '/internal': 'http://127.0.0.1:8001',
    },
  },
  build: { outDir: 'dist' },
})
