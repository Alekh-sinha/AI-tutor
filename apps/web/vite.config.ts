import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // the API (uvicorn on :8000) is reached as /api/* so the browser never needs its address or any key
  server: { proxy: { '/api': { target: process.env.API_URL || 'http://localhost:8000', ws: true, rewrite: (p) => p.replace(/^\/api/, '') } } },
})
