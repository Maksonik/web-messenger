import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin proxy: the refresh cookie and the WebSocket work without CORS.
    proxy: {
      '/api': { target: backendUrl, ws: true },
    },
  },
})
