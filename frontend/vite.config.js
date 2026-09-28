import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  server: {
    /* Vite refuses requests whose Host header it does not recognise - a
       defence against DNS rebinding, where a hostile page points a domain it
       controls at your machine and reads what answers. A tunnel arrives with
       the tunnel's hostname, so it is refused until named here.
       ngrok's free tier hands out a NEW hostname every restart, so these are
       the domain suffixes rather than one host - otherwise this file needs
       editing every time the tunnel comes up. */
    allowedHosts: ['.ngrok-free.dev', '.ngrok-free.app', '.ngrok.io', '.ngrok.app'],

    /* The API goes through this server rather than being called directly.

       Without it the browser is told to fetch http://127.0.0.1:8000 - which is
       the API on the machine running the BROWSER, not the one running the app.
       On your own laptop those are the same thing and it works; for anyone you
       share a tunnel with they are not, and every request dies on their own
       empty port 8000.

       Proxied, the page and the API are one origin: one tunnel is enough,
       there is no CORS to configure, and nothing has to know the tunnel's
       name. `changeOrigin` presents the backend with a Host it expects. */
    proxy: {
      '/api': {
        // Override to run a second copy beside the usual one.
        target: process.env.SCORECARD_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        /* Pass on who is really asking (X-Forwarded-For). Without it every
           row in the activity log reads 127.0.0.1 - this proxy's own address.
           The backend trusts the header from 127.0.0.1 only. */
        xfwd: true,
      },
    },
  },
})
