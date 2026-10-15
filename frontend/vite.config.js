// Vite config: the dev server forwards /api to the backend.
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],

  server: {
    allowedHosts: ['.ngrok-free.dev', '.ngrok-free.app', '.ngrok.io', '.ngrok.app'],

    proxy: {
      '/api': {
        target: process.env.SCORECARD_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        xfwd: true,
      },
    },
  },
})
