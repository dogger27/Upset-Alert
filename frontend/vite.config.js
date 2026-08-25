import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Stamp dist/sw.js with a per-build SW_VERSION. The service worker only
// updates installed PWAs when its bytes change; the manual stamp in
// public/sw.js went unbumped through 12 straight deploys on 2026-08-24
// and pinned every installed client to a stale bundle. (Rebuilt after the
// 2026-08-25 baseline restore deleted the first version of this plugin.)
function stampServiceWorker() {
  return {
    name: 'stamp-service-worker',
    apply: 'build',
    closeBundle() {
      const f = path.resolve(__dirname, 'dist/sw.js')
      if (!fs.existsSync(f)) return
      const stamped = fs.readFileSync(f, 'utf8').replace(
        /const SW_VERSION = '[^']*'/,
        `const SW_VERSION = '${new Date().toISOString()}'`,
      )
      fs.writeFileSync(f, stamped)
    },
  }
}

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

export default defineConfig({
  plugins: [react(), buildTimePlugin(), stampServiceWorker()],
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
