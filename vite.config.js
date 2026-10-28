import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'node:child_process'

// Baked into the bundle at build time so any device can be asked which
// version it is running (shown on the Profile page). Falls back to a
// timestamp when git is unavailable.
let buildId = ''
try {
  buildId = execSync('git rev-parse --short HEAD').toString().trim()
} catch {
  buildId = ''
}
if (!buildId) buildId = Date.now().toString(36)

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_BUILD__: JSON.stringify(buildId),
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
