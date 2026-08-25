import fs from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function buildTimePlugin() {
  return {
    name: 'build-time',
    configureServer(server) {
      server.watcher.on('change', (file) => {
        if (/src[/\\].*\.(jsx?|css|tsx?|js)$/.test(file)) {
          server.ws.send({
            type: 'custom',
            event: 'build-time-update',
            data: { time: new Date().toISOString() },
          })
        }
      })
    },
  }
}

// Stamp sw.js with a per-build version. The worker's SW_VERSION bump is what
// forces every installed PWA onto the current bundle (see public/sw.js) — and
// it was a MANUAL bump, so twelve deploys on 2026-08-25 shipped while every
// installed app kept running the previous day's JS, reporting each fix as
// "still broken". The build does the bumping now; a deploy and a forced
// convergence are the same event.
const stampServiceWorker = () => ({
  name: 'stamp-sw-version',
  closeBundle() {
    const path = 'dist/sw.js'
    if (!fs.existsSync(path)) return
    const stamped = fs.readFileSync(path, 'utf8').replace(
      /const SW_VERSION = '[^']*'/,
      `const SW_VERSION = '${new Date().toISOString()}'`)
    fs.writeFileSync(path, stamped)
  },
})

export default defineConfig({
  plugins: [stampServiceWorker(), react(), buildTimePlugin()],
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
