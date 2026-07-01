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

export default defineConfig({
  plugins: [react(), buildTimePlugin()],
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
